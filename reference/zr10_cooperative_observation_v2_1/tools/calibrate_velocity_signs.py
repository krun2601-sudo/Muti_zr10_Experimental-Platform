"""Safely measure how +yaw/+pitch SDK velocity commands change feedback angles."""
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import argparse
import asyncio
from siyi_sdk import configure_logging, connect_udp
from zr10_coop.angle_utils import normalize_zr10_pitch, wrap_to_180
from zr10_coop.config import load_config


def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument('--config', default='config/three_zr10.yaml')
    p.add_argument('--speed', type=int, default=10)
    p.add_argument('--pulse', type=float, default=0.35)
    p.add_argument('--sdk-log-level', default='WARNING')
    return p.parse_args()

async def read(client):
    a=await client.get_gimbal_attitude()
    return float(a.yaw_deg), normalize_zr10_pitch(float(a.pitch_deg))

async def stop(client):
    try: await client.rotate(yaw=0,pitch=0)
    except Exception: await client.rotate_nowait(yaw=0,pitch=0)

async def pulse(client,yaw,pitch,duration):
    before=await read(client)
    await client.rotate(yaw=yaw,pitch=pitch)
    await asyncio.sleep(duration)
    await stop(client)
    await asyncio.sleep(0.3)
    after=await read(client)
    return before,after

async def one(g,speed,duration):
    print(f'\n[{g.id}] {g.ip}')
    async with await connect_udp(g.ip,g.control_port,timeout=g.command_timeout_s,max_retries=g.max_retries) as c:
        await c.get_firmware_version(); await stop(c)
        y0,y1=await pulse(c,speed,0,duration)
        dy=wrap_to_180(y1[0]-y0[0])
        # return approximately
        await c.rotate(yaw=-speed,pitch=0); await asyncio.sleep(duration); await stop(c); await asyncio.sleep(.3)
        p0,p1=await pulse(c,0,speed,duration)
        dp=p1[1]-p0[1]
        # return approximately
        await c.rotate(yaw=0,pitch=-speed); await asyncio.sleep(duration); await stop(c)
        print(f'  +yaw command: feedback delta={dy:+.2f} deg -> yaw_velocity_sign={1.0 if dy>0 else -1.0}')
        print(f'  +pitch command: feedback delta={dp:+.2f} deg -> pitch_velocity_sign={1.0 if dp>0 else -1.0}')

async def amain():
    a=parse_args(); configure_logging(level=a.sdk_log_level)
    if not 1<=a.speed<=25: raise ValueError('--speed must be 1..25')
    if not .2<=a.pulse<=.6: raise ValueError('--pulse must be 0.2..0.6')
    cfg=load_config(Path(a.config).resolve())
    for g in cfg.enabled_gimbals():
        try: await one(g,a.speed,a.pulse)
        except Exception as e: print(f'  FAILED: {type(e).__name__}: {e}')
        await asyncio.sleep(cfg.system.connect_stagger_s)

if __name__=='__main__': asyncio.run(amain())
