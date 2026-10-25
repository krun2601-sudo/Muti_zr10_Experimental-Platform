## main scenario means
| scenario | method | research_missed_target_rate | research_detection_delay_censored_p95_s | research_total_loss_s | research_max_loss_gap_s | research_revisit_age_p95_s |
| --- | --- | --- | --- | --- | --- | --- |
| S0-no-target | classical_ptz | 0 | 0 | 0 | 0 | 6.4 |
| S0-no-target | ecprh | 0 | 0 | 0 | 0 | 6.85 |
| S0-no-target | fixed_scan | 0 | 0 | 0 | 0 | 13.7 |
| S0-no-target | greedy | 0 | 0 | 0 | 0 | 11.4 |
| S0-no-target | info_planner | 0 | 0 | 0 | 0 | 5.4 |
| S0-no-target | ssm_belief | 0 | 0 | 0 | 0 | 6.4 |
| S0-no-target | weighted_rh | 0 | 0 | 0 | 0 | 37.8 |
| S10-heldout-mixed | classical_ptz | 0 | 14.21 | 34.5 | 2.505 | 7.739 |
| S10-heldout-mixed | ecprh | 0 | 13.27 | 10.12 | 1.485 | 6.599 |
| S10-heldout-mixed | fixed_scan | 0 | 25.94 | 106.8 | 1.84 | 52.11 |
| S10-heldout-mixed | greedy | 0 | 13.39 | 146.8 | 6.41 | 16.02 |
| S10-heldout-mixed | info_planner | 0 | 4.656 | 173.1 | 10.1 | 7.108 |
| S10-heldout-mixed | ssm_belief | 0 | 7.488 | 46.81 | 3.145 | 7.077 |
| S10-heldout-mixed | weighted_rh | 0 | 15.13 | 9.52 | 2.025 | 19.11 |
| S11-heldout-handoff-contention | classical_ptz | 0 | 9.811 | 51.54 | 3.165 | 7.831 |
| S11-heldout-handoff-contention | ecprh | 0 | 7.122 | 11.91 | 1.515 | 6.257 |
| S11-heldout-handoff-contention | fixed_scan | 0 | 20.76 | 140 | 1.82 | 90.32 |
| S11-heldout-handoff-contention | greedy | 0 | 11.78 | 151.7 | 10.41 | 21.45 |
| S11-heldout-handoff-contention | info_planner | 0 | 6.743 | 180.5 | 9.005 | 7.743 |
| S11-heldout-handoff-contention | ssm_belief | 0 | 6.048 | 45.4 | 3.455 | 7.312 |
| S11-heldout-handoff-contention | weighted_rh | 0 | 5.361 | 14.07 | 2.27 | 35.1 |
| S7-overload | classical_ptz | 0.03333 | 32.68 | 77.04 | 5.935 | 7.918 |
| S7-overload | ecprh | 0.008333 | 28.34 | 24.55 | 2.06 | 6.8 |
| S7-overload | fixed_scan | 0.025 | 50.86 | 146.4 | 4.795 | 53.71 |
| S7-overload | greedy | 0.01667 | 21.27 | 244.5 | 9.275 | 18.73 |
| S7-overload | info_planner | 0 | 4.758 | 283.3 | 12 | 7.637 |
| S7-overload | ssm_belief | 0 | 10.72 | 79.49 | 12.19 | 6.887 |
| S7-overload | weighted_rh | 0.01667 | 33.55 | 41.01 | 9.34 | 21.83 |

## ood scenario means
| scenario | method | research_missed_target_rate | research_detection_delay_censored_p95_s | research_total_loss_s | research_max_loss_gap_s | research_revisit_age_p95_s |
| --- | --- | --- | --- | --- | --- | --- |
| S9a-ood-fast-targets | classical_ptz | 0 | 5.314 | 5.91 | 1.815 | 12.29 |
| S9a-ood-fast-targets | ecprh | 0 | 6.509 | 3.035 | 1.615 | 9.54 |
| S9a-ood-fast-targets | fixed_scan | 0 | 11.35 | 36.21 | 2.015 | 22.52 |
| S9a-ood-fast-targets | greedy | 0.08333 | 14.22 | 39.3 | 6.91 | 24.35 |
| S9a-ood-fast-targets | info_planner | 0 | 4.376 | 49.3 | 7.165 | 7.439 |
| S9a-ood-fast-targets | ssm_belief | 0 | 4.811 | 13.62 | 2.205 | 10.41 |
| S9a-ood-fast-targets | weighted_rh | 0.01667 | 7.116 | 5.565 | 3.095 | 23 |
| S9b-ood-delay-noise | classical_ptz | 0 | 8.241 | 30.43 | 8.11 | 8.447 |
| S9b-ood-delay-noise | ecprh | 0 | 7.045 | 22.21 | 6.82 | 8.965 |
| S9b-ood-delay-noise | fixed_scan | 0 | 12.76 | 92.8 | 25.58 | 24.1 |
| S9b-ood-delay-noise | greedy | 0 | 11.01 | 89.08 | 18.69 | 25.99 |
| S9b-ood-delay-noise | info_planner | 0 | 7.356 | 87.53 | 9.725 | 8.235 |
| S9b-ood-delay-noise | ssm_belief | 0 | 12.74 | 37.75 | 6.685 | 8.867 |
| S9b-ood-delay-noise | weighted_rh | 0 | 11.28 | 17.28 | 6.775 | 41.78 |

## sensitivity means
| scenario | parameter | value | research_missed_target_rate | research_detection_delay_censored_p95_s | research_total_loss_s | research_max_loss_gap_s | research_revisit_age_p95_s | solve_ms_p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S4-boundary-handoff | policy.research.execution.settle_s | 0.1 | 0 | 1.7 | 0.58 | 0.34 | 7.716 | 32.65 |
| S4-boundary-handoff | policy.research.execution.settle_s | 0.25 | 0 | 5.22 | 1.96 | 1 | 9.272 | 31.61 |
| S4-boundary-handoff | policy.research.execution.settle_s | 0.5 | 0 | 0.5 | 1.38 | 1 | 11.77 | 30.21 |
| S4-boundary-handoff | policy.research.perception.detection_probability | 0.8 | 0 | 5.24 | 2.04 | 1 | 9.444 | 31.24 |
| S4-boundary-handoff | policy.research.perception.detection_probability | 0.9 | 0 | 5.22 | 1.82 | 1 | 9.284 | 33.53 |
| S4-boundary-handoff | policy.research.perception.detection_probability | 0.96 | 0 | 5.22 | 1.96 | 1 | 9.272 | 32.72 |
| S4-boundary-handoff | policy.research.perception.detection_probability | 1 | 0 | 5.2 | 1.56 | 1 | 9.566 | 33.36 |
| S4-boundary-handoff | policy.research.perception.position_noise_std_m | 0.25 | 0 | 5.22 | 1.96 | 1 | 8.872 | 24.11 |
| S4-boundary-handoff | policy.research.perception.position_noise_std_m | 0.5 | 0 | 5.22 | 2.22 | 1 | 10.35 | 24.07 |
| S4-boundary-handoff | policy.research.perception.position_noise_std_m | 1 | 0 | 5.22 | 1.96 | 1 | 9.272 | 22.19 |
| S4-boundary-handoff | policy.research.perception.position_noise_std_m | 2 | 0 | 5.22 | 2.02 | 1 | 8.878 | 22.43 |
| S4-boundary-handoff | policy.research.perception.position_noise_std_m | 4 | 0 | 5.22 | 3.06 | 1.38 | 9.5 | 21.89 |
| S4-boundary-handoff | policy.research.planning.horizon_s | 1 | 0 | 1.92 | 65.8 | 65.8 | 84.9 | 5.039 |
| S4-boundary-handoff | policy.research.planning.horizon_s | 2 | 0 | 6.4 | 1.82 | 0.84 | 8.956 | 17.99 |
| S4-boundary-handoff | policy.research.planning.horizon_s | 3 | 0 | 5.22 | 1.96 | 1 | 9.272 | 23.59 |
| S4-boundary-handoff | policy.research.planning.horizon_s | 4 | 0 | 4.34 | 2.5 | 0.78 | 9.252 | 38.45 |
| S4-boundary-handoff | policy.research.planning.horizon_s | 5 | 0 | 5.3 | 2.62 | 0.78 | 9.18 | 48 |
| S4-boundary-handoff | policy.research.planning.replan_period_s | 0.25 | 0 | 4 | 8.98 | 3.16 | 10.95 | 21.54 |
| S4-boundary-handoff | policy.research.planning.replan_period_s | 0.5 | 0 | 5.22 | 1.96 | 1 | 9.272 | 22.38 |
| S4-boundary-handoff | policy.research.planning.replan_period_s | 1 | 0 | 2.9 | 0.66 | 0.48 | 9.88 | 23.3 |
| S4-boundary-handoff | policy.research.planning.visibility_risk | 0.01 | 0 | 5.22 | 2.44 | 1 | 9.676 | 20.55 |
| S4-boundary-handoff | policy.research.planning.visibility_risk | 0.025 | 0 | 5.22 | 2.36 | 1 | 8.902 | 20.99 |
| S4-boundary-handoff | policy.research.planning.visibility_risk | 0.05 | 0 | 5.22 | 1.96 | 1 | 9.272 | 21.63 |
| S4-boundary-handoff | policy.research.planning.visibility_risk | 0.1 | 0 | 5.22 | 1.74 | 0.9 | 9.174 | 21.88 |
| S4-boundary-handoff | policy.research.planning.visibility_risk | 0.2 | 0 | 5.22 | 1.82 | 0.78 | 8.306 | 22.05 |
| S8-maneuver | policy.research.execution.settle_s | 0.1 | 0 | 2.505 | 4.12 | 2.7 | 7.264 | 36.57 |
| S8-maneuver | policy.research.execution.settle_s | 0.25 | 0 | 4.157 | 5.98 | 3.68 | 8.84 | 34.44 |
| S8-maneuver | policy.research.execution.settle_s | 0.5 | 0 | 3.93 | 5.38 | 2.44 | 10 | 31.71 |
| S8-maneuver | policy.research.perception.detection_probability | 0.8 | 0 | 4.56 | 5.16 | 2.7 | 8.79 | 33.71 |
| S8-maneuver | policy.research.perception.detection_probability | 0.9 | 0 | 4.142 | 6.38 | 3.38 | 8.962 | 34.82 |
| S8-maneuver | policy.research.perception.detection_probability | 0.96 | 0 | 4.157 | 5.98 | 3.68 | 8.84 | 34.78 |
| S8-maneuver | policy.research.perception.detection_probability | 1 | 0 | 4.292 | 6.1 | 3.64 | 8.046 | 37.76 |
| S8-maneuver | policy.research.perception.position_noise_std_m | 0.25 | 0 | 4.074 | 5.76 | 3.62 | 9.41 | 23.49 |
| S8-maneuver | policy.research.perception.position_noise_std_m | 0.5 | 0 | 4.071 | 6.68 | 3.64 | 7.79 | 22.77 |
| S8-maneuver | policy.research.perception.position_noise_std_m | 1 | 0 | 4.157 | 5.98 | 3.68 | 8.84 | 22.04 |
| S8-maneuver | policy.research.perception.position_noise_std_m | 2 | 0 | 4.763 | 6.3 | 3.7 | 8.46 | 24.83 |
| S8-maneuver | policy.research.perception.position_noise_std_m | 4 | 0 | 4.076 | 7.16 | 3.1 | 9.012 | 24.44 |
| S8-maneuver | policy.research.planning.horizon_s | 1 | 0 | 56.43 | 78 | 73.3 | 94.9 | 4.688 |
| S8-maneuver | policy.research.planning.horizon_s | 2 | 0 | 6.442 | 4.76 | 3.26 | 9.24 | 15.64 |
| S8-maneuver | policy.research.planning.horizon_s | 3 | 0 | 4.157 | 5.98 | 3.68 | 8.84 | 22.92 |
| S8-maneuver | policy.research.planning.horizon_s | 4 | 0 | 2.574 | 7.08 | 4.16 | 7.9 | 31.89 |
| S8-maneuver | policy.research.planning.horizon_s | 5 | 0 | 2.54 | 9.22 | 4.2 | 8.12 | 44.83 |
| S8-maneuver | policy.research.planning.replan_period_s | 0.25 | 0 | 3.514 | 12.52 | 4.28 | 9.606 | 23.63 |
| S8-maneuver | policy.research.planning.replan_period_s | 0.5 | 0 | 4.157 | 5.98 | 3.68 | 8.84 | 23.64 |
| S8-maneuver | policy.research.planning.replan_period_s | 1 | 0 | 2.679 | 4.82 | 2.98 | 9.32 | 24.92 |
| S8-maneuver | policy.research.planning.visibility_risk | 0.01 | 0 | 4.127 | 6.94 | 4.14 | 7.21 | 23.34 |
| S8-maneuver | policy.research.planning.visibility_risk | 0.025 | 0 | 4.167 | 4.96 | 3.22 | 8.098 | 23.71 |
| S8-maneuver | policy.research.planning.visibility_risk | 0.05 | 0 | 4.157 | 5.98 | 3.68 | 8.84 | 23.77 |
| S8-maneuver | policy.research.planning.visibility_risk | 0.1 | 0 | 4.461 | 5.76 | 2.56 | 9.842 | 23.29 |
| S8-maneuver | policy.research.planning.visibility_risk | 0.2 | 0 | 4.553 | 4.24 | 3.2 | 9.376 | 22.91 |

## ablation means
| scenario | variant | research_missed_target_rate | research_detection_delay_censored_p95_s | research_total_loss_s | research_max_loss_gap_s | research_revisit_age_p95_s | research_handover_success_rate | research_empirical_risk_violation_rate | research_risk_prediction_trials | research_replan_frequency_hz | research_event_replan_count | priority_certification_rate | solver_timeout_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S11-heldout-handoff-contention | full | 0 | 7.122 | 11.91 | 1.515 | 6.257 | 0.9816 | 0 | 200.8 | 3.365 | 215.7 | 0.8238 | 0.0003245 |
| S11-heldout-handoff-contention | no_event_replan | 0 | 5.683 | 9.685 | 1.34 | 6.647 | 0.9954 | 0 | 353.9 | 1.991 | 0 | 0.8361 | 0.001667 |
| S11-heldout-handoff-contention | no_overlap | 0 | 6.788 | 12.33 | 1.37 | 6.905 | 0.9847 | 0 | 202.8 | 3.349 | 211.7 | 0.7893 | 0.0003329 |
| S2-staggered | fixed_zoom | 0 | 10.15 | 14.61 | 5.855 | 12.2 | 0.9946 | 0 | 88.15 | 2.833 | 147.5 | 0.9675 | 0.000188 |
| S2-staggered | full | 0 | 4.228 | 5.375 | 3.03 | 6.922 | 0.9868 | 0.0004545 | 110 | 2.739 | 119.3 | 0.9371 | 0.002635 |
| S2-staggered | no_event_replan | 0 | 4.571 | 6.045 | 4.005 | 7.177 | 0.9895 | 0.0003125 | 155.3 | 1.991 | 0 | 0.9489 | 0.003889 |
| S4-boundary-handoff | full | 0 | 5.22 | 1.96 | 1 | 9.272 | 0.9857 | 0 | 101.4 | 2.662 | 88.2 | 0.9959 | 0.001042 |
| S4-boundary-handoff | no_event_replan | 0 | 5.22 | 1.74 | 1 | 9.1 | 0.9909 | 0 | 122.8 | 1.989 | 0 | 0.9933 | 0.001333 |
| S4-boundary-handoff | no_execution_model | 1 | 69.8 | 0 | 0 | 84.9 | NA | NA | 0 | 1.989 | 0 | 1 | 0 |
| S4-boundary-handoff | no_overlap | 0 | 5.22 | 2.08 | 1 | 8.448 | 0.9895 | 0 | 101.8 | 2.636 | 85.4 | 0.999 | 0 |
| S4-boundary-handoff | short_horizon | 0 | 1.92 | 65.8 | 65.8 | 84.9 | NA | NA | 0 | 2.499 | 65 | 1 | 0 |
| S5-cluster-split | fixed_zoom | 0 | 0 | 18.98 | 3.445 | 64.7 | 0.9986 | 0.0002315 | 212.3 | 3.668 | 239.9 | 0.8848 | 0 |
| S5-cluster-split | full | 0 | 2.055 | 7.2 | 1.215 | 36.16 | 0.9981 | 0 | 228.6 | 3.554 | 205.4 | 0.8373 | 0.0001812 |
| S5-cluster-split | no_shared_fov | 0 | 2.055 | 7.38 | 1.46 | 36.91 | 0.998 | 0 | 230.4 | 3.552 | 205.2 | 0.8484 | 0.0001773 |
| S6-contention | fixed_zoom | 0 | 17.68 | 20.54 | 2.935 | 12.26 | 0.9866 | 0 | 135.8 | 3.249 | 212.3 | 0.9236 | 0 |
| S6-contention | full | 0 | 6.72 | 8.925 | 1.475 | 6.769 | 0.9941 | 0.0003067 | 166.1 | 3.214 | 189.7 | 0.8893 | 0.0008437 |
| S6-contention | no_shared_fov | 0 | 7.073 | 7.92 | 1.51 | 6.69 | 0.9982 | 0.0003268 | 165.6 | 3.211 | 189.5 | 0.8842 | 0.0005194 |
| S6-contention | short_horizon | 0.25 | 38.08 | 102.7 | 46.7 | 99.9 | NA | 0.03214 | 4.9 | 3.251 | 178.2 | 1 | 0 |
| S8-maneuver | full | 0 | 4.157 | 5.98 | 3.68 | 8.84 | 0.9765 | 0 | 125.2 | 2.782 | 119.4 | 0.9781 | 0 |
| S8-maneuver | no_uncertainty | 0 | 4.36 | 3.96 | 3.08 | 8.45 | 1 | 0 | 133.8 | 2.664 | 99 | 0.9948 | 0 |
| S9a-ood-fast-targets | full | 0 | 6.509 | 3.035 | 1.615 | 9.54 | 0.9846 | 0 | 63 | 2.585 | 85.35 | 0.975 | 0.001692 |
| S9a-ood-fast-targets | no_execution_model | 1 | 52.17 | 0 | 0 | 89.9 | NA | NA | 0 | 1.99 | 0 | 0.9938 | 0.00625 |
| S9a-ood-fast-targets | no_uncertainty | 0 | 6.095 | 2.055 | 1.67 | 8.685 | 0.9566 | 0 | 70.75 | 2.539 | 76 | 0.9846 | 0.003415 |
| S9b-ood-delay-noise | full | 0 | 7.045 | 22.21 | 6.82 | 8.965 | 0.9712 | 0 | 64.25 | 3.598 | 208.2 | 0.8941 | 0.003274 |
| S9b-ood-delay-noise | no_execution_model | 1 | 44.8 | 0 | 0 | 94.9 | NA | NA | 0 | 1.991 | 0 | 1 | 0 |
| S9b-ood-delay-noise | no_uncertainty | 0 | 4.175 | 5.39 | 2.515 | 7.82 | 0.9591 | 0.001494 | 70.35 | 3.942 | 251.1 | 0.9466 | 0.003443 |

## main runtime and risk
| method | research_handover_success_rate | research_empirical_risk_violation_rate | research_risk_prediction_trials | research_replan_frequency_hz | research_event_replan_count | priority_certification_rate | solver_timeout_rate | solve_ms_p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| classical_ptz | 0.9715 | NA | 0 | 3.165 | 187.8 | NA | 0 | 0 |
| ecprh | 0.9879 | 0 | 149.3 | 3.075 | 166.2 | 0.8782 | 0.002564 | 43.8 |
| fixed_scan | 0.2627 | NA | 0 | 2.793 | 175.1 | NA | NA | NA |
| greedy | 0.4844 | NA | 0 | 2.741 | 138.9 | NA | 0 | 0 |
| info_planner | 0.5358 | NA | 0 | 2.614 | 100.1 | NA | 0 | 0 |
| ssm_belief | 0.9469 | NA | 0 | 3.033 | 164.7 | NA | 0 | 0 |
| weighted_rh | 0.9951 | 8.46e-05 | 149.8 | 3.04 | 163.8 | NA | 0 | 9.243 |