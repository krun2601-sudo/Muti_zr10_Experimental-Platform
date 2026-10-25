"""Reproduce report tables/figures from frozen geometry-v2 CSVs; never rerun experiments.
Usage: python build_analysis.py --data /path/to/geometry_v2 --out /path/to/analysis
Requires numpy, pandas, matplotlib. Missing values are never imputed.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

METRICS=['research_missed_target_rate','research_detection_delay_censored_p95_s','research_total_loss_s','research_max_loss_gap_s','research_revisit_age_p95_s']
SHORT=['Miss rate','Detection P95 (s)','Total loss (s)','Max loss (s)','Revisit P95 (s)']
METHODS=['fixed_scan','greedy','weighted_rh','classical_ptz','info_planner','ssm_belief','ecprh']
LABELS=['Fixed scan','Greedy','Weighted RH','Classical PTZ','Info planner','SSM belief','ECP-RH']

def boot(a):
 a=np.asarray(a,dtype=float);a=a[np.isfinite(a)]
 if not len(a):return np.nan,np.nan
 r=np.random.default_rng(20261025)
 x=r.choice(a,size=(10000,len(a)),replace=True).mean(axis=1)
 return tuple(np.percentile(x,[2.5,97.5]))

def summary(d,keys):
 rows=[]
 for key,g in d.groupby(keys,sort=True):
  if not isinstance(key,tuple):key=(key,)
  for m in METRICS+['solve_ms_p95','solver_timeout_rate','research_handover_success_rate','research_empirical_risk_violation_rate']:
   a=pd.to_numeric(g[m],errors='coerce').dropna().to_numpy()
   lo,hi=boot(a)
   rows.append(dict(zip(keys,key))|dict(metric=m,n=len(a),mean=float(np.mean(a)) if len(a) else np.nan,sd=float(np.std(a,ddof=1)) if len(a)>1 else np.nan,bootstrap95_low=lo,bootstrap95_high=hi))
 return pd.DataFrame(rows)

def md(d):
 def f(x):
  if pd.isna(x):return 'NA'
  if isinstance(x,(float,np.floating)):return f'{x:.4g}'
  return str(x)
 return '| '+' | '.join(d.columns)+' |\n| '+' | '.join(['---']*len(d.columns))+' |\n'+'\n'.join('| '+' | '.join(map(f,row))+' |' for row in d.itertuples(index=False,name=None))

def main():
 here=Path(__file__).resolve().parent
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data','--source',type=Path,default=here.parent/'results/geometry_v2');p.add_argument('--out','--output',type=Path,default=here);a=p.parse_args()
 root=a.data.resolve();out=a.out.resolve();tab=out/'tables';fig=out/'figures';tab.mkdir(parents=True,exist_ok=True);fig.mkdir(parents=True,exist_ok=True)
 data={k:pd.read_csv(root/k/'run_metrics.csv') for k in ['main','ood','ablations','sensitivity']}
 audit={};source_hashes={}
 for k,d in data.items():
  keys=['scenario','seed','method'];duplicates=int(d.duplicated(keys).sum());complete=int(d.status.eq('completed').sum())
  audit[k]={'rows':len(d),'completed':complete,'duplicates':duplicates,'scenario_counts':d.groupby('scenario').size().to_dict()}
  assert not duplicates and complete==len(d) and len(d)=={'main':560,'ood':280,'ablations':415,'sensitivity':250}[k]
  summary(d,['scenario','method']).to_csv(tab/f'{k}_scenario_summary.csv',index=False,encoding='utf-8-sig')
  for f in ['run_metrics.csv','paired_comparisons.csv']:
   src=root/k/f
   if src.exists():source_hashes[f'{k}/{f}']=hashlib.sha256(src.read_bytes()).hexdigest()
 for k in ['main','ood']:
  d=data[k];summary(d,['method']).to_csv(tab/f'{k}_overall_summary.csv',index=False,encoding='utf-8-sig')
  wide=d.groupby('method')[METRICS].mean().reindex(METHODS);wide.to_csv(tab/f'{k}_overall_means.csv',encoding='utf-8-sig')
  pairs=pd.read_csv(root/k/'paired_comparisons.csv');pairs=pairs[pairs.metric.isin(METRICS)]
  pairs.to_csv(tab/f'{k}_primary_paired_statistics.csv',index=False,encoding='utf-8-sig')
 summary(data['main'][data['main'].scenario.ne('S0-no-target')],['method']).to_csv(tab/'main_target_present_summary.csv',index=False,encoding='utf-8-sig')
 # The merged ablation CSV repeats '__all__' overall rows from scenario shards.
 # Use scenario-scoped rows only and preserve each scenario's comparison family.
 ap=pd.read_csv(root/'ablations/paired_comparisons.csv');ap=ap[(ap.scope=='scenario') & ap.metric.isin(METRICS)]
 assert not ap.duplicated(['scenario','metric','competitor']).any()
 ap.to_csv(tab/'ablation_primary_paired_statistics.csv',index=False,encoding='utf-8-sig')
 sen=data['sensitivity'].copy();parsed=sen.method.str.extract(r'ecprh\[(.+)=([^=]+)\]');sen['parameter']=parsed[0];sen['value']=parsed[1].astype(float)
 ss=summary(sen,['scenario','parameter','value']);ss.to_csv(tab/'sensitivity_summary.csv',index=False,encoding='utf-8-sig')
 sc=pd.read_csv(root/'scalability/scalability.csv');assert len(sc)==24 and sc.repetitions.eq(10).all()
 sc['generation_plus_solve_mean_ms']=sc.generation_ms_mean+sc.solve_ms_mean
 sc.to_csv(tab/'scalability_timing.csv',index=False,encoding='utf-8-sig')
 audit['scalability']={'points':len(sc),'repetitions_each':10,'duplicate_points':int(sc.duplicated(['device_count','target_count','search_candidates_per_device']).sum())}
 audit['source_sha256']=source_hashes;audit['software']={'python':sys.version.split()[0],'numpy':np.__version__,'pandas':pd.__version__,'matplotlib':matplotlib.__version__};audit['notes']=['All five primary metrics are minimized.','New descriptive CIs use 10000 percentile bootstrap resamples, seed 20261025; published paired statistics are copied, not recomputed.','Paired statistics Holm families are metric-by-scenario/scope, not all outcomes jointly.','Ablation overall rows are shard-local; use scenario rows.','Timing totals use sums of means only; sums of marginal P95s are not presented as joint P95.']
 (out/'analysis_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
 plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':220})
 # Main and OOD comparisons: report existing paired confidence intervals.
 for k in ['main','ood']:
  pairs=pd.read_csv(root/k/'paired_comparisons.csv');pairs=pairs[pairs.scope.eq('overall')]
  f,axes=plt.subplots(1,3,figsize=(12.4,4.1))
  for ax,m,label in zip(axes,[METRICS[1],METRICS[2],METRICS[4]],[SHORT[1],SHORT[2],SHORT[4]]):
   t=pairs[pairs.metric.eq(m)].set_index('competitor').reindex(METHODS[:-1]);y=np.arange(len(t));v=t.paired_mean_reference_advantage.to_numpy();lo=t.bootstrap95_low.to_numpy();hi=t.bootstrap95_high.to_numpy()
   ax.errorbar(v,y,xerr=np.vstack([v-lo,hi-v]),fmt='o',capsize=3,color='#235789');ax.axvline(0,color='gray',lw=1);ax.set_yticks(y,LABELS[:-1] if ax is axes[0] else ['']*len(y));ax.invert_yaxis();ax.set_title(label);ax.grid(axis='x',alpha=.2);ax.set_xlabel('Comparator minus ECP-RH')
  f.suptitle(f'{k.upper()} paired effects: positive favors ECP-RH',fontsize=12);f.tight_layout();f.savefig(fig/f'{k}_paired_effects.png');plt.close(f)
 # Loss by scenario, with actual source values and descriptive bootstrap CIs.
 d=data['main'];summ=summary(d,['scenario','method']);f,axes=plt.subplots(1,3,figsize=(12.4,4.2))
 for ax,scenario in zip(axes,[s for s in sorted(d.scenario.unique()) if s!='S0-no-target']):
  t=summ[(summ.scenario==scenario)&(summ.metric==METRICS[2])].set_index('method').reindex(METHODS);x=np.arange(7);v=t['mean'].to_numpy();lo=t.bootstrap95_low.to_numpy();hi=t.bootstrap95_high.to_numpy()
  ax.bar(x,v,color=['#91b6cd']*6+['#c33c54']);ax.errorbar(x,v,yerr=np.vstack([v-lo,hi-v]),fmt='none',color='black',capsize=2);ax.set_xticks(x,LABELS,rotation=65,ha='right',fontsize=8);ax.set_title(scenario.split('-')[0]);ax.set_ylabel('Post-discovery total loss / s');ax.grid(axis='y',alpha=.2)
 f.tight_layout();f.savefig(fig/'main_loss_by_scenario.png');plt.close(f)
 # Six parameter sensitivity panels, separate scenarios, 5 seeds per point.
 paths=sorted(sen.parameter.unique())
 for m,name in [(METRICS[2],'total_loss'),(METRICS[4],'revisit_age')]:
  f,axes=plt.subplots(2,3,figsize=(12.4,7.0))
  for ax,path in zip(axes.flat,paths):
   for scenario,g in ss[(ss.parameter==path)&(ss.metric==m)].groupby('scenario'):
    g=g.sort_values('value');x=g.value.to_numpy();v=g['mean'].to_numpy();lo=g.bootstrap95_low.to_numpy();hi=g.bootstrap95_high.to_numpy();ax.errorbar(x,v,yerr=np.vstack([v-lo,hi-v]),marker='o',capsize=3,label=scenario.split('-')[0])
   ax.set_title(path.split('.')[-1]);ax.set_xlabel('Parameter value');ax.set_ylabel('Mean / s');ax.grid(alpha=.2);ax.legend(fontsize=8)
  f.suptitle(f'Sensitivity: {name.replace("_"," ")} (5 seeds per scenario/value)',fontsize=12);f.tight_layout();f.savefig(fig/f'sensitivity_{name}.png');plt.close(f)
 # Scalability separates generation and solve to avoid false end-to-end timing claim.
 f,axes=plt.subplots(1,3,figsize=(12.4,4.0))
 for level,g in sc.groupby('search_candidates_per_device'):
  for ax,col,label in zip(axes,['generation_ms_p95','solve_ms_p95','priority_certification_rate'],['Candidate generation P95 / ms','MILP solve P95 / ms','Full priority certification rate']):ax.plot(g.target_count,g[col],marker='o',label=f'K={level}');ax.set_xlabel('Target count');ax.set_ylabel(label);ax.grid(alpha=.2)
 for ax in axes:ax.legend(fontsize=8)
 axes[1].axhline(120,color='gray',linestyle='--',lw=1);f.tight_layout();f.savefig(fig/'scalability_breakdown.png');plt.close(f)
 # Selected ablations: each row is a scenario-matched contrast, including adverse effects.
 chosen=[('S2-staggered','ecprh[fixed_zoom]'),('S5-cluster-split','ecprh[fixed_zoom]'),('S6-contention','ecprh[short_horizon]'),('S11-heldout-handoff-contention','ecprh[no_event_replan]'),('S9b-ood-delay-noise','ecprh[no_uncertainty]')]
 f,ax=plt.subplots(figsize=(9.5,4.4))
 for y,(s,c) in enumerate(chosen):
  z=ap[(ap.scenario==s)&(ap.competitor==c)&(ap.metric==METRICS[2])].iloc[0];v=z.paired_mean_reference_advantage;ax.errorbar(v,y,xerr=[[v-z.bootstrap95_low],[z.bootstrap95_high-v]],fmt='o',capsize=3,color='#235789')
 ax.set_yticks(range(len(chosen)),[s.split('-')[0]+' / '+c[6:-1] for s,c in chosen]);ax.invert_yaxis();ax.axvline(0,color='gray',lw=1);ax.set_xlabel('Ablation minus full model: total loss / s');ax.set_title('Scenario-matched ablations: positive favors full model');ax.grid(axis='x',alpha=.2);f.tight_layout();f.savefig(fig/'ablation_loss_effects.png');plt.close(f)
 # Compact numeric evidence for narrative authoring.
 chunks=[]
 for k in ['main','ood']:
  chunks.append(f'## {k} scenario means\n'+md(data[k].groupby(['scenario','method'])[METRICS].mean().reset_index()))
 chunks.append('## sensitivity means\n'+md(sen.groupby(['scenario','parameter','value'])[METRICS+['solve_ms_p95']].mean().reset_index()))
 extras=['research_handover_success_rate','research_empirical_risk_violation_rate','research_risk_prediction_trials','research_replan_frequency_hz','research_event_replan_count','priority_certification_rate','solver_timeout_rate']
 chunks.append('## ablation means\n'+md(data['ablations'].groupby(['scenario','variant'])[METRICS+extras].mean().reset_index()))
 chunks.append('## main runtime and risk\n'+md(data['main'].groupby('method')[extras+['solve_ms_p95']].mean().reset_index()))
 (out/'numeric_evidence.md').write_text('\n\n'.join(chunks),encoding='utf-8')
 print(json.dumps({'tables':len(list(tab.glob('*.csv'))),'figures':len(list(fig.glob('*.png'))),'audit':audit},ensure_ascii=False))

if __name__=='__main__':main()
