# The Atlas: why systems fail together, and what that leaves for votes, selection and depth

Session E5, section 4.4. Written by `python -m analysis.atlas_analyses` from research/v4/atlas/data/ (sources and hashes in its MANIFEST.md); definitions in the script's docstring and in autoagentnet/atlas/factor.py. Exploratory throughout: public leaderboard data, one fit per benchmark, nothing here is a test. Fits use a ridge of 0.1 on every coefficient, so items every system gets right (or wrong) get large but finite difficulties; the L0 share depends on that ridge. Left out: matharena/arxivmath-training (one system answers its 2,605 items, so their difficulty is not identified).

Complete items x systems matrices used by A2, A5 and A7 (systems that answered at least 95% of the items, then the items all of them answered):

| benchmark | items | systems |
|---|---|---|
| swebench_verified | 500 | 173 |
| livebench/LCB_generation | 78 | 150 |
| livebench/coding_completion | 50 | 149 |
| livebench/typos | 98 | 61 |
| matharena/aime_2025 | 30 | 66 |
| matharena/hmmt_feb_2025 | 29 | 64 |
| matharena/smt_2025 | 52 | 43 |
| matharena/apex_shortlist | 45 | 39 |
| matharena/arxivmath-0626 | 48 | 32 |
| matharena/hmmt_feb_2026 | 33 | 31 |
| bbeh_phase1 | 300 | 4 |

## A1. Systematic failure share

| source | family | items | systems | accuracy | share_L0 | share_L1_median | heldout_ll_base | heldout_ll_L0 | heldout_ll_L1 |
|---|---|---|---|---|---|---|---|---|---|
| swebench_verified | (all) | 500 | 173 | 0.535 | 0.728 | 0.769 | 0.702 | 0.312 | 0.311 |
| swebench_verified | swebench_verified | 500 | 173 | 0.535 | 0.728 |  |  |  |  |
| matharena | (all) | 733 | 126 | 0.714 | 0.732 | 0.805 | 0.541 | 0.240 | 0.268 |
| matharena | matharena/aime_2025 | 30 | 67 | 0.744 | 0.670 |  |  |  |  |
| matharena | matharena/aime_2026 | 30 | 32 | 0.949 | 0.444 |  |  |  |  |
| matharena | matharena/apex_2025 | 12 | 48 | 0.158 | 0.148 |  |  |  |  |
| matharena | matharena/apex_shortlist | 47 | 44 | 0.640 | 0.298 |  |  |  |  |
| matharena | matharena/arxivmath-0126 | 23 | 28 | 0.586 | 0.722 |  |  |  |  |
| matharena | matharena/arxivmath-0226 | 32 | 27 | 0.404 | 0.674 |  |  |  |  |
| matharena | matharena/arxivmath-0326 | 30 | 17 | 0.527 | 0.637 |  |  |  |  |
| matharena | matharena/arxivmath-0426 | 40 | 27 | 0.484 | 0.683 |  |  |  |  |
| matharena | matharena/arxivmath-0526 | 40 | 32 | 0.595 | 0.692 |  |  |  |  |
| matharena | matharena/arxivmath-0626 | 48 | 32 | 0.646 | 0.627 |  |  |  |  |
| matharena | matharena/arxivmath-1225 | 17 | 21 | 0.436 | 0.747 |  |  |  |  |
| matharena | matharena/brumo_2025 | 30 | 44 | 0.901 | 0.497 |  |  |  |  |
| matharena | matharena/cmimc_2025 | 40 | 35 | 0.798 | 0.556 |  |  |  |  |
| matharena | matharena/hmmt_feb_2025 | 30 | 64 | 0.650 | 0.570 |  |  |  |  |
| matharena | matharena/hmmt_feb_2026 | 33 | 32 | 0.880 | 0.516 |  |  |  |  |
| matharena | matharena/hmmt_nov_2025 | 30 | 22 | 0.900 | 0.546 |  |  |  |  |
| matharena | matharena/kangaroo_2025_1-2 | 24 | 23 | 0.750 | 0.587 |  |  |  |  |
| matharena | matharena/kangaroo_2025_11-12 | 30 | 23 | 0.928 | 0.380 |  |  |  |  |
| matharena | matharena/kangaroo_2025_3-4 | 24 | 23 | 0.632 | 0.571 |  |  |  |  |
| matharena | matharena/kangaroo_2025_5-6 | 30 | 21 | 0.725 | 0.626 |  |  |  |  |
| matharena | matharena/kangaroo_2025_7-8 | 30 | 22 | 0.886 | 0.530 |  |  |  |  |
| matharena | matharena/kangaroo_2025_9-10 | 30 | 22 | 0.952 | 0.345 |  |  |  |  |
| matharena | matharena/smt_2025 | 53 | 43 | 0.830 | 0.689 |  |  |  |  |
| livebench | (all) | 228 | 165 | 0.401 | 0.649 | 0.733 | 0.680 | 0.360 | 0.355 |
| livebench | livebench/LCB_generation | 78 | 157 | 0.406 | 0.730 |  |  |  |  |
| livebench | livebench/coding_completion | 50 | 157 | 0.354 | 0.542 |  |  |  |  |
| livebench | livebench/typos | 100 | 160 | 0.428 | 0.597 |  |  |  |  |
| bbeh_phase1 | (all) | 300 | 4 | 0.589 | 0.424 | 0.620 | 0.780 | 0.690 | 0.817 |
| bbeh_phase1 | bbeh/boolean expressions | 75 | 4 | 0.633 | 0.411 |  |  |  |  |
| bbeh_phase1 | bbeh/dyck languages | 75 | 4 | 0.637 | 0.378 |  |  |  |  |
| bbeh_phase1 | bbeh/geometric shapes | 75 | 4 | 0.527 | 0.503 |  |  |  |  |
| bbeh_phase1 | bbeh/web of lies | 75 | 4 | 0.560 | 0.333 |  |  |  |  |

## A2. The tail: all-wrong rate of random k-sets, observed vs models (in-sample)

| k | observed | independent | L0 | L1 | L2 | copula | rho | benchmark | items | systems |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.4651 | 0.4651 | 0.4651 | 0.4651 | 0.4651 | 0.4651 | 0.7580 | swebench_verified | 500 | 173 |
| 2 | 0.3038 | 0.2016 | 0.3026 | 0.3031 | 0.3030 | 0.3019 | 0.7580 | swebench_verified | 500 | 173 |
| 3 | 0.2547 | 0.1024 | 0.2550 | 0.2548 | 0.2546 | 0.2500 | 0.7580 | swebench_verified | 500 | 173 |
| 4 | 0.2123 | 0.0434 | 0.2114 | 0.2123 | 0.2122 | 0.1993 | 0.7580 | swebench_verified | 500 | 173 |
| 5 | 0.2002 | 0.0235 | 0.1992 | 0.2004 | 0.2001 | 0.1845 | 0.7580 | swebench_verified | 500 | 173 |
| 1 | 0.5932 | 0.5932 | 0.5927 | 0.5928 | 0.5928 | 0.5932 | 0.8723 | livebench/LCB_generation | 78 | 150 |
| 2 | 0.4579 | 0.3514 | 0.4563 | 0.4570 | 0.4567 | 0.4581 | 0.8723 | livebench/LCB_generation | 78 | 150 |
| 3 | 0.3800 | 0.2074 | 0.3799 | 0.3804 | 0.3797 | 0.3841 | 0.8723 | livebench/LCB_generation | 78 | 150 |
| 4 | 0.3528 | 0.1279 | 0.3505 | 0.3527 | 0.3518 | 0.3583 | 0.8723 | livebench/LCB_generation | 78 | 150 |
| 5 | 0.2955 | 0.0663 | 0.2898 | 0.2929 | 0.2923 | 0.3014 | 0.8723 | livebench/LCB_generation | 78 | 150 |
| 1 | 0.6427 | 0.6427 | 0.6420 | 0.6419 | 0.6419 | 0.6427 | 0.6331 | livebench/coding_completion | 50 | 149 |
| 2 | 0.4719 | 0.4072 | 0.4696 | 0.4707 | 0.4700 | 0.4701 | 0.6331 | livebench/coding_completion | 50 | 149 |
| 3 | 0.4099 | 0.2978 | 0.4056 | 0.4081 | 0.4070 | 0.4062 | 0.6331 | livebench/coding_completion | 50 | 149 |
| 4 | 0.3254 | 0.1838 | 0.3289 | 0.3274 | 0.3258 | 0.3272 | 0.6331 | livebench/coding_completion | 50 | 149 |
| 5 | 0.2697 | 0.1026 | 0.2687 | 0.2698 | 0.2687 | 0.2650 | 0.6331 | livebench/coding_completion | 50 | 149 |
| 1 | 0.4778 | 0.4778 | 0.4778 | 0.4778 | 0.4778 | 0.4778 | 0.6108 | livebench/typos | 98 | 61 |
| 2 | 0.3162 | 0.2240 | 0.3188 | 0.3193 | 0.3189 | 0.3187 | 0.6108 | livebench/typos | 98 | 61 |
| 3 | 0.2479 | 0.1108 | 0.2460 | 0.2477 | 0.2468 | 0.2481 | 0.6108 | livebench/typos | 98 | 61 |
| 4 | 0.1956 | 0.0515 | 0.1957 | 0.1973 | 0.1963 | 0.2003 | 0.6108 | livebench/typos | 98 | 61 |
| 5 | 0.1567 | 0.0240 | 0.1603 | 0.1606 | 0.1591 | 0.1667 | 0.6108 | livebench/typos | 98 | 61 |
| 1 | 0.2561 | 0.2561 | 0.2589 | 0.2589 | 0.2588 | 0.2561 | 0.8115 | matharena/aime_2025 | 30 | 66 |
| 2 | 0.1215 | 0.0743 | 0.1225 | 0.1236 | 0.1233 | 0.1226 | 0.8115 | matharena/aime_2025 | 30 | 66 |
| 3 | 0.0557 | 0.0117 | 0.0579 | 0.0586 | 0.0583 | 0.0537 | 0.8115 | matharena/aime_2025 | 30 | 66 |
| 4 | 0.0483 | 0.0034 | 0.0462 | 0.0482 | 0.0481 | 0.0408 | 0.8115 | matharena/aime_2025 | 30 | 66 |
| 5 | 0.0367 | 0.0010 | 0.0371 | 0.0378 | 0.0377 | 0.0308 | 0.8115 | matharena/aime_2025 | 30 | 66 |
| 1 | 0.3400 | 0.3400 | 0.3417 | 0.3422 | 0.3422 | 0.3400 | 0.6837 | matharena/hmmt_feb_2025 | 29 | 64 |
| 2 | 0.1528 | 0.1122 | 0.1530 | 0.1550 | 0.1549 | 0.1518 | 0.6837 | matharena/hmmt_feb_2025 | 29 | 64 |
| 3 | 0.0731 | 0.0315 | 0.0722 | 0.0741 | 0.0739 | 0.0720 | 0.6837 | matharena/hmmt_feb_2025 | 29 | 64 |
| 4 | 0.0509 | 0.0148 | 0.0520 | 0.0530 | 0.0529 | 0.0520 | 0.6837 | matharena/hmmt_feb_2025 | 29 | 64 |
| 5 | 0.0352 | 0.0059 | 0.0336 | 0.0350 | 0.0349 | 0.0347 | 0.6837 | matharena/hmmt_feb_2025 | 29 | 64 |
| 1 | 0.1561 | 0.1561 | 0.1593 | 0.1581 | 0.1581 | 0.1561 | 0.8351 | matharena/smt_2025 | 52 | 43 |
| 2 | 0.0815 | 0.0237 | 0.0814 | 0.0835 | 0.0833 | 0.0820 | 0.8351 | matharena/smt_2025 | 52 | 43 |
| 3 | 0.0595 | 0.0035 | 0.0597 | 0.0618 | 0.0615 | 0.0574 | 0.8351 | matharena/smt_2025 | 52 | 43 |
| 4 | 0.0532 | 0.0006 | 0.0511 | 0.0526 | 0.0525 | 0.0459 | 0.8351 | matharena/smt_2025 | 52 | 43 |
| 5 | 0.0467 | 0.0001 | 0.0440 | 0.0454 | 0.0453 | 0.0354 | 0.8351 | matharena/smt_2025 | 52 | 43 |
| 1 | 0.3595 | 0.3595 | 0.3604 | 0.3605 | 0.3605 | 0.3595 | 0.3253 | matharena/apex_shortlist | 45 | 39 |
| 2 | 0.1731 | 0.1455 | 0.1802 | 0.1788 | 0.1781 | 0.1767 | 0.3253 | matharena/apex_shortlist | 45 | 39 |
| 3 | 0.0774 | 0.0449 | 0.0825 | 0.0828 | 0.0815 | 0.0808 | 0.3253 | matharena/apex_shortlist | 45 | 39 |
| 4 | 0.0424 | 0.0172 | 0.0462 | 0.0456 | 0.0447 | 0.0454 | 0.3253 | matharena/apex_shortlist | 45 | 39 |
| 5 | 0.0226 | 0.0052 | 0.0260 | 0.0277 | 0.0273 | 0.0268 | 0.3253 | matharena/apex_shortlist | 45 | 39 |
| 1 | 0.3535 | 0.3535 | 0.3548 | 0.3544 | 0.3544 | 0.3535 | 0.7159 | matharena/arxivmath-0626 | 48 | 32 |
| 2 | 0.1956 | 0.1233 | 0.1948 | 0.1973 | 0.1971 | 0.1948 | 0.7159 | matharena/arxivmath-0626 | 48 | 32 |
| 3 | 0.1377 | 0.0437 | 0.1347 | 0.1379 | 0.1378 | 0.1323 | 0.7159 | matharena/arxivmath-0626 | 48 | 32 |
| 4 | 0.1043 | 0.0147 | 0.1001 | 0.1024 | 0.1025 | 0.0957 | 0.7159 | matharena/arxivmath-0626 | 48 | 32 |
| 5 | 0.0881 | 0.0057 | 0.0844 | 0.0876 | 0.0873 | 0.0790 | 0.7159 | matharena/arxivmath-0626 | 48 | 32 |
| 1 | 0.1193 | 0.1193 | 0.1245 | 0.1235 | 0.1235 | 0.1193 | 0.7223 | matharena/hmmt_feb_2026 | 33 | 31 |
| 2 | 0.0439 | 0.0135 | 0.0453 | 0.0472 | 0.0471 | 0.0440 | 0.7223 | matharena/hmmt_feb_2026 | 33 | 31 |
| 3 | 0.0265 | 0.0016 | 0.0240 | 0.0268 | 0.0268 | 0.0236 | 0.7223 | matharena/hmmt_feb_2026 | 33 | 31 |
| 4 | 0.0127 | 0.0002 | 0.0145 | 0.0148 | 0.0147 | 0.0150 | 0.7223 | matharena/hmmt_feb_2026 | 33 | 31 |
| 5 | 0.0058 | 0.0000 | 0.0088 | 0.0093 | 0.0091 | 0.0098 | 0.7223 | matharena/hmmt_feb_2026 | 33 | 31 |
| 1 | 0.4108 | 0.4108 | 0.4111 | 0.4111 | 0.4111 | 0.4108 | 0.1650 | bbeh_phase1 | 300 | 4 |
| 2 | 0.1533 | 0.1421 | 0.1718 | 0.1789 | 0.1766 | 0.1533 | 0.1650 | bbeh_phase1 | 300 | 4 |
| 3 | 0.0492 | 0.0358 | 0.0656 | 0.0757 | 0.0727 | 0.0470 | 0.1650 | bbeh_phase1 | 300 | 4 |
| 4 | 0.0100 | 0.0032 | 0.0170 | 0.0230 | 0.0226 | 0.0077 | 0.1650 | bbeh_phase1 | 300 | 4 |

## A3. Vote vs selection, systems with repeats

| benchmark | systems | items | k | vote@k | pass@k | vote ceiling (all calls) | coverage@k | best single in set |
|---|---|---|---|---|---|---|---|---|
| matharena/aime_2025 | 64 | 29 | 1 | 0.744 | 0.744 | 0.767 | 0.763 | 0.763 |
| matharena/aime_2025 | 64 | 29 | 2 | 0.741 | 0.788 | 0.767 | 0.905 | 0.892 |
| matharena/aime_2025 | 64 | 29 | 3 | 0.760 | 0.806 | 0.767 | 0.954 | 0.941 |
| matharena/aime_2025 | 64 | 29 | 4 | 0.767 | 0.816 | 0.767 | 0.962 | 0.954 |
| matharena/hmmt_feb_2025 | 63 | 29 | 1 | 0.651 | 0.651 | 0.662 | 0.658 | 0.658 |
| matharena/hmmt_feb_2025 | 63 | 29 | 2 | 0.641 | 0.696 | 0.662 | 0.846 | 0.829 |
| matharena/hmmt_feb_2025 | 63 | 29 | 3 | 0.657 | 0.723 | 0.662 | 0.935 | 0.911 |
| matharena/hmmt_feb_2025 | 63 | 29 | 4 | 0.662 | 0.737 | 0.662 | 0.950 | 0.927 |
| matharena/smt_2025 | 42 | 52 | 1 | 0.830 | 0.830 | 0.850 | 0.841 | 0.841 |
| matharena/smt_2025 | 42 | 52 | 2 | 0.830 | 0.864 | 0.850 | 0.914 | 0.891 |
| matharena/smt_2025 | 42 | 52 | 3 | 0.847 | 0.876 | 0.850 | 0.939 | 0.917 |
| matharena/smt_2025 | 42 | 52 | 4 | 0.850 | 0.883 | 0.850 | 0.946 | 0.922 |
| matharena/apex_shortlist | 38 | 44 | 1 | 0.628 | 0.628 | 0.679 | 0.666 | 0.666 |
| matharena/apex_shortlist | 38 | 44 | 2 | 0.628 | 0.742 | 0.679 | 0.849 | 0.776 |
| matharena/apex_shortlist | 38 | 44 | 3 | 0.663 | 0.789 | 0.679 | 0.943 | 0.860 |
| matharena/apex_shortlist | 38 | 44 | 4 | 0.679 | 0.822 | 0.679 | 0.962 | 0.873 |
| bbeh_phase1 | 2 | 300 | 1 | 0.332 | 0.332 | 0.346 | 0.332 | 0.332 |
| bbeh_phase1 | 2 | 300 | 2 | 0.308 | 0.433 | 0.346 | 0.540 | 0.440 |
| bbeh_phase1 | 2 | 300 | 3 | 0.325 | 0.520 | 0.346 |  |  |
| bbeh_phase1 | 2 | 300 | 4 | 0.337 | 0.563 | 0.346 |  |  |
| bbeh_phase1 | 2 | 300 | 5 | 0.346 | 0.605 | 0.346 |  |  |

## A4. Selection efficiency of label-free policies (ratio of means over random k-sets)

gain = policy accuracy minus the best single system of the set (that system is chosen with labels); eta divides the gain by the room above the best single system (coverage minus best), so it swings widely where that room is a few points.

| benchmark | repeats | k | sets | best single | coverage | plurality acc | plurality gain | plurality eta | Dawid-Skene acc | Dawid-Skene gain | Dawid-Skene eta | Dawid-Skene, all repeats acc | Dawid-Skene, all repeats gain | Dawid-Skene, all repeats eta | pooled Dawid-Skene acc | pooled Dawid-Skene gain | pooled Dawid-Skene eta | shortest output acc | shortest output gain | shortest output eta | lowest cost acc | lowest cost gain | lowest cost eta | fewest steps acc | fewest steps gain | fewest steps eta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| matharena/aime_2025 | 4.000 | 3 | 60 | 0.933 | 0.949 | 0.863 | -0.070 | -4.369 | 0.878 | -0.056 | -3.464 | 0.948 | 0.014 | 0.893 | 0.943 | 0.009 | 0.571 | 0.673 | -0.260 | -16.179 | 0.675 | -0.259 | -16.071 |  |  |  |
| matharena/aime_2025 | 4.000 | 5 | 60 | 0.963 | 0.974 | 0.936 | -0.027 | -2.500 | 0.957 | -0.006 | -0.579 | 0.966 | 0.003 | 0.263 | 0.965 | 0.002 | 0.158 | 0.677 | -0.286 | -26.211 | 0.730 | -0.233 | -21.368 |  |  |  |
| matharena/hmmt_feb_2025 | 4.000 | 3 | 60 | 0.894 | 0.918 | 0.765 | -0.129 | -5.217 | 0.801 | -0.093 | -3.767 | 0.901 | 0.007 | 0.302 | 0.783 | -0.110 | -4.465 | 0.549 | -0.344 | -13.930 | 0.536 | -0.358 | -14.488 |  |  |  |
| matharena/hmmt_feb_2025 | 4.000 | 5 | 60 | 0.959 | 0.976 | 0.881 | -0.078 | -4.530 | 0.930 | -0.028 | -1.633 | 0.959 | 0.001 | 0.033 | 0.957 | -0.001 | -0.067 | 0.513 | -0.445 | -25.833 | 0.588 | -0.371 | -21.500 |  |  |  |
| matharena/arxivmath-0626 | 3.000 | 3 | 60 | 0.850 | 0.880 | 0.722 | -0.128 | -4.247 | 0.745 | -0.105 | -3.482 | 0.850 | -0.000 | -0.000 | 0.799 | -0.051 | -1.682 | 0.723 | -0.127 | -4.212 | 0.515 | -0.335 | -11.118 |  |  |  |
| matharena/arxivmath-0626 | 3.000 | 5 | 60 | 0.886 | 0.914 | 0.748 | -0.138 | -4.925 | 0.806 | -0.080 | -2.861 | 0.849 | -0.037 | -1.316 | 0.844 | -0.043 | -1.519 | 0.729 | -0.157 | -5.608 | 0.372 | -0.514 | -18.342 |  |  |  |
| swebench_verified (39 with details) |  | 3 | 60 | 0.709 | 0.782 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 0.556 | -0.153 | -2.086 | 0.582 | -0.127 | -1.737 |
| swebench_verified (39 with details) |  | 5 | 60 | 0.736 | 0.821 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 0.456 | -0.281 | -3.317 | 0.500 | -0.236 | -2.796 |
| bbeh_phase1 |  | 3 | 4 | 0.910 | 0.951 | 0.553 | -0.357 | -8.745 | 0.588 | -0.322 | -7.878 |  |  |  |  |  |  | 0.453 | -0.457 | -11.184 | 0.278 | -0.633 | -15.490 |  |  |  |

Dawid-Skene on every system with 4 repeats (plain: every call a witness; pooled: one soft vote per system):

| benchmark | systems | items | best system | true accuracy | plain estimate | plain rank | plain rank corr | pooled estimate | pooled rank | pooled rank corr |
|---|---|---|---|---|---|---|---|---|---|---|
| matharena/aime_2025 | 66 | 30 | glm/glm-47 | 1.000 | 0.990 | 1 | 0.994 | 0.990 | 1 | 0.994 |
| matharena/hmmt_feb_2025 | 64 | 30 | openai/gpt-52 | 1.000 | 0.990 | 1 | 0.997 | 0.990 | 1 | 0.997 |
| matharena/smt_2025 | 43 | 53 | openai/gpt-52 | 0.985 | 0.940 | 3 | 0.808 | 0.940 | 3 | 0.825 |
| matharena/arxivmath-0626 | 28 | 48 | openai/gpt-6-astra | 0.944 | 0.833 | 4 | 0.939 | 0.833 | 4 | 0.937 |

## A5. Compositional prediction on held-out systems and items

Coverage of k-sets of held-out systems on held-out items: mean signed error (bias) and mean absolute error of the factor model (L1), and the MAE of independence, with 95% item-bootstrap intervals. An absolute error is biased upward under resampling, so an interval can sit above its estimate.

| k | sets | observed coverage | model bias | model MAE | model lo | model hi | independent MAE | independent lo | independent hi | fit_systems | held_systems | test_items | benchmark |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 87 | 0.5166 | -0.0058 | 0.0217 | 0.0234 | 0.0325 | 0.0234 | 0.0253 | 0.0479 | 86 | 87 | 250 | swebench_verified |
| 2 | 200 | 0.6541 | 0.0009 | 0.0183 | 0.0192 | 0.0276 | 0.1090 | 0.0726 | 0.1451 | 86 | 87 | 250 | swebench_verified |
| 3 | 200 | 0.7196 | 0.0003 | 0.0183 | 0.0184 | 0.0266 | 0.1662 | 0.1171 | 0.2128 | 86 | 87 | 250 | swebench_verified |
| 4 | 200 | 0.7567 | 0.0029 | 0.0164 | 0.0159 | 0.0246 | 0.1892 | 0.1521 | 0.2326 | 86 | 87 | 250 | swebench_verified |
| 5 | 200 | 0.7788 | 0.0057 | 0.0150 | 0.0146 | 0.0227 | 0.1954 | 0.1559 | 0.2393 | 86 | 87 | 250 | swebench_verified |
| 1 | 75 | 0.3870 | 0.0208 | 0.0424 | 0.0429 | 0.0661 | 0.0868 | 0.0540 | 0.1806 | 75 | 75 | 39 | livebench/LCB_generation |
| 2 | 200 | 0.4815 | 0.0258 | 0.0440 | 0.0424 | 0.0705 | 0.1986 | 0.1033 | 0.3184 | 75 | 75 | 39 | livebench/LCB_generation |
| 3 | 200 | 0.5947 | 0.0273 | 0.0492 | 0.0428 | 0.0785 | 0.2611 | 0.1537 | 0.3635 | 75 | 75 | 39 | livebench/LCB_generation |
| 4 | 200 | 0.6428 | 0.0178 | 0.0442 | 0.0407 | 0.0747 | 0.2829 | 0.1864 | 0.4003 | 75 | 75 | 39 | livebench/LCB_generation |
| 5 | 200 | 0.6744 | 0.0231 | 0.0457 | 0.0434 | 0.0765 | 0.2825 | 0.1922 | 0.3651 | 75 | 75 | 39 | livebench/LCB_generation |
| 1 | 75 | 0.4101 | -0.0061 | 0.0663 | 0.0697 | 0.1016 | 0.0827 | 0.0725 | 0.1751 | 74 | 75 | 25 | livebench/coding_completion |
| 2 | 200 | 0.5876 | -0.0053 | 0.0695 | 0.0710 | 0.1091 | 0.0767 | 0.0816 | 0.1516 | 74 | 75 | 25 | livebench/coding_completion |
| 3 | 200 | 0.7032 | -0.0118 | 0.0604 | 0.0596 | 0.1012 | 0.0670 | 0.0696 | 0.1428 | 74 | 75 | 25 | livebench/coding_completion |
| 4 | 200 | 0.7740 | -0.0021 | 0.0539 | 0.0462 | 0.0968 | 0.0746 | 0.0567 | 0.1757 | 74 | 75 | 25 | livebench/coding_completion |
| 5 | 200 | 0.8174 | -0.0087 | 0.0493 | 0.0416 | 0.0965 | 0.0826 | 0.0521 | 0.1814 | 74 | 75 | 25 | livebench/coding_completion |
| 1 | 31 | 0.5484 | -0.0026 | 0.0527 | 0.0502 | 0.0862 | 0.0639 | 0.0520 | 0.1312 | 30 | 31 | 49 | livebench/typos |
| 2 | 200 | 0.6935 | 0.0152 | 0.0382 | 0.0398 | 0.0745 | 0.0718 | 0.0468 | 0.1546 | 30 | 31 | 49 | livebench/typos |
| 3 | 200 | 0.7729 | 0.0169 | 0.0369 | 0.0350 | 0.0660 | 0.1170 | 0.0544 | 0.1948 | 30 | 31 | 49 | livebench/typos |
| 4 | 200 | 0.8102 | 0.0193 | 0.0348 | 0.0292 | 0.0683 | 0.1348 | 0.0649 | 0.2226 | 30 | 31 | 49 | livebench/typos |
| 5 | 200 | 0.8480 | 0.0127 | 0.0301 | 0.0250 | 0.0565 | 0.1275 | 0.0577 | 0.2065 | 30 | 31 | 49 | livebench/typos |
| 1 | 33 | 0.7556 | -0.0333 | 0.0747 | 0.0682 | 0.1055 | 0.0667 | 0.0707 | 0.1314 | 33 | 33 | 15 | matharena/aime_2025 |
| 2 | 200 | 0.8920 | 0.0012 | 0.0461 | 0.0292 | 0.0973 | 0.0552 | 0.0357 | 0.1727 | 33 | 33 | 15 | matharena/aime_2025 |
| 3 | 200 | 0.9327 | 0.0180 | 0.0387 | 0.0112 | 0.1052 | 0.0550 | 0.0130 | 0.1827 | 33 | 33 | 15 | matharena/aime_2025 |
| 4 | 200 | 0.9443 | 0.0268 | 0.0348 | 0.0030 | 0.0938 | 0.0528 | 0.0031 | 0.1509 | 33 | 33 | 15 | matharena/aime_2025 |
| 5 | 200 | 0.9503 | 0.0329 | 0.0350 | 0.0005 | 0.1023 | 0.0491 | 0.0006 | 0.1431 | 33 | 33 | 15 | matharena/aime_2025 |
| 1 | 32 | 0.5813 | 0.0405 | 0.1042 | 0.0929 | 0.1575 | 0.1451 | 0.0917 | 0.2556 | 32 | 32 | 15 | matharena/hmmt_feb_2025 |
| 2 | 200 | 0.7780 | 0.0679 | 0.1070 | 0.0644 | 0.1751 | 0.1536 | 0.0716 | 0.2633 | 32 | 32 | 15 | matharena/hmmt_feb_2025 |
| 3 | 200 | 0.8537 | 0.0675 | 0.0868 | 0.0461 | 0.1437 | 0.1221 | 0.0483 | 0.2163 | 32 | 32 | 15 | matharena/hmmt_feb_2025 |
| 4 | 200 | 0.9130 | 0.0521 | 0.0612 | 0.0246 | 0.1198 | 0.0808 | 0.0263 | 0.1525 | 32 | 32 | 15 | matharena/hmmt_feb_2025 |
| 5 | 200 | 0.9387 | 0.0444 | 0.0484 | 0.0126 | 0.1044 | 0.0601 | 0.0121 | 0.1315 | 32 | 32 | 15 | matharena/hmmt_feb_2025 |
| 1 | 22 | 0.8199 | 0.0095 | 0.0523 | 0.0466 | 0.0943 | 0.0699 | 0.0559 | 0.1713 | 21 | 22 | 26 | matharena/smt_2025 |
| 2 | 200 | 0.8771 | 0.0512 | 0.0559 | 0.0223 | 0.1184 | 0.1054 | 0.0290 | 0.2210 | 21 | 22 | 26 | matharena/smt_2025 |
| 3 | 200 | 0.8925 | 0.0590 | 0.0601 | 0.0080 | 0.1255 | 0.1048 | 0.0073 | 0.2183 | 21 | 22 | 26 | matharena/smt_2025 |
| 4 | 200 | 0.9044 | 0.0676 | 0.0677 | 0.0016 | 0.1381 | 0.0953 | 0.0009 | 0.1989 | 21 | 22 | 26 | matharena/smt_2025 |
| 5 | 200 | 0.9075 | 0.0749 | 0.0749 | 0.0010 | 0.1621 | 0.0925 | 0.0008 | 0.2002 | 21 | 22 | 26 | matharena/smt_2025 |
| 1 | 20 | 0.6478 | -0.0047 | 0.1009 | 0.0922 | 0.1511 | 0.0984 | 0.0917 | 0.1506 | 19 | 20 | 23 | matharena/apex_shortlist |
| 2 | 190 | 0.8551 | 0.0093 | 0.0675 | 0.0568 | 0.1043 | 0.0656 | 0.0587 | 0.1056 | 19 | 20 | 23 | matharena/apex_shortlist |
| 3 | 200 | 0.9241 | 0.0125 | 0.0458 | 0.0362 | 0.0736 | 0.0457 | 0.0357 | 0.0758 | 19 | 20 | 23 | matharena/apex_shortlist |
| 4 | 200 | 0.9711 | 0.0059 | 0.0239 | 0.0161 | 0.0440 | 0.0236 | 0.0157 | 0.0409 | 19 | 20 | 23 | matharena/apex_shortlist |
| 5 | 200 | 0.9852 | 0.0061 | 0.0140 | 0.0078 | 0.0288 | 0.0141 | 0.0067 | 0.0280 | 19 | 20 | 23 | matharena/apex_shortlist |
| 1 | 16 | 0.6484 | -0.0138 | 0.0693 | 0.0591 | 0.1194 | 0.0885 | 0.0651 | 0.1798 | 16 | 16 | 24 | matharena/arxivmath-0626 |
| 2 | 120 | 0.7799 | 0.0125 | 0.0459 | 0.0380 | 0.0792 | 0.1331 | 0.0509 | 0.2656 | 16 | 16 | 24 | matharena/arxivmath-0626 |
| 3 | 200 | 0.8258 | 0.0333 | 0.0421 | 0.0288 | 0.0841 | 0.1499 | 0.0623 | 0.2648 | 16 | 16 | 24 | matharena/arxivmath-0626 |
| 4 | 200 | 0.8444 | 0.0435 | 0.0451 | 0.0215 | 0.0940 | 0.1483 | 0.0352 | 0.2656 | 16 | 16 | 24 | matharena/arxivmath-0626 |
| 5 | 200 | 0.8679 | 0.0486 | 0.0489 | 0.0206 | 0.0987 | 0.1304 | 0.0362 | 0.2489 | 16 | 16 | 24 | matharena/arxivmath-0626 |
| 1 | 16 | 0.8787 | 0.0046 | 0.0664 | 0.0454 | 0.1146 | 0.0659 | 0.0526 | 0.1239 | 15 | 16 | 17 | matharena/hmmt_feb_2026 |
| 2 | 120 | 0.9549 | 0.0197 | 0.0368 | 0.0088 | 0.0904 | 0.0398 | 0.0111 | 0.1025 | 15 | 16 | 17 | matharena/hmmt_feb_2026 |
| 3 | 200 | 0.9729 | 0.0179 | 0.0269 | 0.0008 | 0.0773 | 0.0268 | 0.0010 | 0.0771 | 15 | 16 | 17 | matharena/hmmt_feb_2026 |
| 4 | 200 | 0.9856 | 0.0106 | 0.0156 | 0.0001 | 0.0465 | 0.0144 | 0.0001 | 0.0430 | 15 | 16 | 17 | matharena/hmmt_feb_2026 |
| 5 | 200 | 0.9909 | 0.0072 | 0.0102 | 0.0000 | 0.0307 | 0.0091 | 0.0000 | 0.0274 | 15 | 16 | 17 | matharena/hmmt_feb_2026 |

3-vote accuracy of held-out MathArena systems (4 repeats) from one-call success and wrong-answer coincidence:

| benchmark | systems | MAE | mean predicted | mean observed |
|---|---|---|---|---|
| matharena/aime_2025 | 32.0000 | 0.0624 | 0.8194 | 0.8208 |
| matharena/apex_shortlist | 19.0000 | 0.0772 | 0.7346 | 0.7153 |
| matharena/hmmt_feb_2025 | 32.0000 | 0.1082 | 0.6400 | 0.5778 |
| matharena/smt_2025 | 21.0000 | 0.0336 | 0.8960 | 0.8974 |

## A6. Depth from public data: one model at two reasoning settings

| benchmark | pair | items | acc low | acc high | a low | a high | delta a | delta a lo | delta a hi | beta low | beta high | delta beta | delta beta lo | delta beta hi | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| swebench_verified | gpt-5.2 default vs high | 500 | 0.690 | 0.718 | 1.229 | 1.656 | 0.427 | 0.084 | 0.865 | 2.269 | 2.826 | 0.558 | 0.058 | 1.278 |  |
| matharena | gpt-5.2 low vs high | 40 | 0.400 | 0.600 | 0.347 | 3.203 | 2.856 | 0.546 | 2.946 | 2.403 | 3.891 | 1.488 | -1.860 | 1.150 |  |
| matharena | gpt-5.2 low vs default | 0 |  |  |  |  |  |  |  |  |  |  |  |  | fewer than 10 shared items |
| matharena | o3-mini low vs medium | 60 | 0.317 | 0.700 | -3.979 | -0.648 | 3.332 | 2.338 | 5.077 | 3.878 | 3.708 | -0.170 | -2.281 | 1.778 |  |
| matharena | o4-mini low vs high | 183 | 0.612 | 0.880 | -1.109 | 1.354 | 2.462 | 1.788 | 3.362 | 2.818 | 2.724 | -0.094 | -1.643 | 2.176 |  |
| matharena | gpt-5-nano low vs default | 30 | 0.500 | 0.867 | -2.270 | 0.640 | 2.910 | 1.263 | 4.854 | 2.804 | 2.587 | -0.216 | -1.310 | 2.529 |  |
| matharena | grok-3-mini low vs high | 183 | 0.563 | 0.809 | -2.329 | 0.382 | 2.712 | 1.933 | 3.766 | 4.431 | 4.184 | -0.246 | -1.803 | 2.287 |  |
| matharena | gemini-3.1-pro low vs default | 55 | 0.400 | 0.673 | 1.163 | 5.101 | 3.938 | 1.135 | 4.320 | 2.946 | 4.590 | 1.645 | -1.758 | 1.951 |  |
| matharena | fable 5.1 low vs max | 88 | 0.477 | 0.886 | 2.305 | 4.910 | 2.606 | 1.129 | 4.448 | 3.107 | 2.478 | -0.628 | -2.456 | 0.440 |  |
| matharena | opus 5.5 high vs max | 88 | 0.830 | 0.830 | 4.427 | 4.495 | 0.068 | -2.379 | 2.317 | 2.424 | 2.476 | 0.053 | -1.546 | 1.433 |  |
| matharena | gpt-6 astra low vs default | 88 | 0.875 | 0.943 | 4.755 | 7.424 | 2.669 | -0.320 | 3.343 | 2.232 | 2.810 | 0.578 | -1.287 | 0.978 |  |

## A7. Price frontier (systems no cheaper system matches)

| benchmark | systems_with_cost | system | accuracy | usd | items |
|---|---|---|---|---|---|
| swebench_verified | 38 | 20251201_mini-v1.17.1_deepseek-v3.2-reasoner | 0.6000 | 0.0281 | 500 |
| swebench_verified | 38 | 20260217_mini-v2.0.0_minimax-2-5-high | 0.7580 | 0.0733 | 500 |
| swebench_verified | 38 | 20260217_mini-v2.0.0_gemini-3-flash-high | 0.7610 | 0.3574 | 498 |
| swebench_verified | 38 | 20260217_mini-v2.0.0_claude-4-5-opus-high | 0.7680 | 0.7539 | 500 |
| bbeh_phase1 | 4 | luna_none | 0.1927 | 0.0001 | 300 |
| bbeh_phase1 | 4 | haiku_nothink | 0.4327 | 0.0007 | 300 |
| bbeh_phase1 | 4 | sol61_low | 0.9675 | 0.0059 | 300 |
| matharena/hmmt_feb_2026 | 29 | qwen/qwen3.5_9b | 0.7121 | 0.0061 | 33 |
| matharena/hmmt_feb_2026 | 29 | xai/grok-41-fast-reasoning | 0.8636 | 0.0071 | 33 |
| matharena/hmmt_feb_2026 | 29 | deepseek/deepseek_v4_flash | 0.9394 | 0.0152 | 33 |
| matharena/hmmt_feb_2026 | 29 | moonshot/k26 | 0.9470 | 0.1343 | 33 |
| matharena/hmmt_feb_2026 | 29 | gemini/gemini-35-flash | 0.9545 | 0.1452 | 33 |
| matharena/hmmt_feb_2026 | 29 | openai/gpt-52-high | 0.9697 | 0.1921 | 33 |
| matharena/hmmt_feb_2026 | 29 | moonshot/k3 | 0.9846 | 0.2241 | 33 |
| matharena/hmmt_feb_2026 | 29 | openai/gpt-55 | 0.9848 | 0.2554 | 33 |
| matharena/arxivmath-0626 | 30 | deepseek/deepseek_v41_flash | 0.5918 | 0.0372 | 48 |
| matharena/arxivmath-0626 | 30 | gemini/gemini-37-flash | 0.6250 | 0.0838 | 48 |
| matharena/arxivmath-0626 | 30 | openai/gpt-6-astra-low | 0.8438 | 0.0876 | 48 |
| matharena/arxivmath-0626 | 30 | openai/gpt-61-sol | 0.9444 | 0.1679 | 48 |
| matharena/aime_2025 | 59 | openai/gpt-5-nano-low | 0.4615 | 0.0009 | 30 |
| matharena/aime_2025 | 59 | xai/grok-3-mini-low | 0.6500 | 0.0029 | 30 |
| matharena/aime_2025 | 59 | xai/grok-4-fast-reasoning | 0.9083 | 0.0046 | 30 |
| matharena/aime_2025 | 59 | deepseek/deepseek_v32 | 0.9167 | 0.0059 | 30 |
| matharena/aime_2025 | 59 | deepseek/deepseek_v32_dec | 0.9417 | 0.0063 | 30 |
| matharena/aime_2025 | 59 | deepseek/deepseek_v32_special | 0.9583 | 0.0093 | 30 |
| matharena/aime_2025 | 59 | stepfun/3.5-flash | 0.9833 | 0.0114 | 30 |
| matharena/aime_2025 | 59 | openai/gpt-52-high | 1.0000 | 0.1090 | 30 |

## F17/F18. SWE-bench Verified, the 39 submissions with per-instance details

| quantity | value |
|---|---|
| systems | 39 |
| items | 500 |
| mean observed failure correlation | 0.5122 |
| mean L0-implied failure correlation | 0.5017 |
| share explained by difficulty alone | 0.9796 |
| same-company pairs | 110 |
| other pairs | 631 |
| residual correlation, same company | 0.0326 |
| residual correlation, other | 0.0066 |
| same-company excess | 0.0260 |
| systematic share (L0) | 0.6917 |
| all-wrong observed | 0.0860 |
| all-wrong independent | 0.0000 |
| all-wrong L0 | 0.0608 |
| all-wrong L1 | 0.0854 |
| all-wrong copula | 0.0553 |
| copula rho | 0.7878 |
| coverage@2 (best pair) | 0.8400 |
| coverage@39 | 0.9140 |
| best single | 0.7680 |
| best single system | 20260217_mini-v2.0.0_claude-4-5-opus-high |
| step AUROC median | 0.6752 |
| step AUROC min | 0.4956 |
| step AUROC max | 0.7894 |
| step AUROC systems | 38 |

Accuracy and mean dollars per instance:

| system | accuracy | usd |
|---|---|---|
| 20260217_mini-v2.0.0_claude-4-5-opus-high | 0.7680 | 0.7539 |
| 20260217_mini-v2.0.0_gemini-3-flash-high | 0.7580 | 0.3560 |
| 20260217_mini-v2.0.0_minimax-2-5-high | 0.7580 | 0.0733 |
| 20260217_mini-v2.0.0_claude-4-6-opus | 0.7560 | 0.5515 |
| 20251124_mini-v1.16.0_claude-opus-4-5-20251101 | 0.7440 | 0.7212 |
| 20251118_mini-v1.15.0_gemini-3-pro-preview-20251118 | 0.7420 | 0.4600 |
| 20260217_mini-v2.0.0_gpt-5-2-high | 0.7280 | 0.4736 |
| 20260217_mini-v2.0.0_glm-5-high | 0.7280 | 0.5344 |
| 20260901_mini-v2.4.2_gemini-3-5-flash | 0.7180 | <NA> |
| 20251211_mini-v1.17.2_gpt-5.2-2025-12-11-high | 0.7180 | 0.5203 |
| 20260217_mini-v2.0.0_claude-4-5-sonnet-high | 0.7140 | 0.6579 |
| 20260217_mini-v2.0.0_kimi-k2-5-high | 0.7080 | 0.1466 |
| 20250929_mini-v1.13.3_sonnet-4-5-20250929 | 0.7060 | 0.5583 |
| 20260217_mini-v2.0.0_deepseek-3-2-high | 0.7000 | 0.4478 |
| 20251211_mini-v1.17.2_gpt-5.2-2025-12-11 | 0.6900 | 0.2697 |
| 20250802_mini-v1.0.0_claude-4-opus-20250514 | 0.6760 | 1.1313 |
| 20260217_mini-v2.0.0_claude-4-5-haiku-high | 0.6660 | 0.3309 |
| 20251120_mini-v1.15.0_gpt-5.1-2025-11-13 | 0.6600 | 0.3062 |
| 20251124_mini-v1.16.0_gpt-5.1-codex | 0.6600 | 0.5889 |
| 20250807_mini-v1.7.0_gpt-5 | 0.6500 | 0.2804 |
| 20250726_mini-v1.0.0_claude-sonnet-4-20250514 | 0.6480 | 0.3715 |
| 20251210_mini-v1.17.2_kimi-k2-thinking | 0.6340 | 0.4383 |
| 20251124_mini-v1.17.0_minimax-m2 | 0.6100 | 0.4283 |
| 20251201_mini-v1.17.1_deepseek-v3.2-reasoner | 0.6000 | 0.0281 |
| 20250807_mini-v1.7.0_gpt-5-mini | 0.5980 | 0.0355 |
| 20250726_mini-v1.0.0_o3-2025-04-16 | 0.5840 | 0.3337 |
| 20251209_mini-v1.17.2_devstral-small-2512 | 0.5640 | 0.2380 |
| 20260217_mini-v2.0.0_gpt-5-mini | 0.5620 | 0.0472 |
| 20251201_mini-v1.17.1_glm-4.6 | 0.5540 | 0.0966 |
| 20250802_mini-v1.0.0_qwen3-coder-480b-a35b-instruct | 0.5540 | 0.2479 |
| 20250822_mini-v1.9.1_glm-4.5 | 0.5420 | 0.2972 |
| 20251209_mini-v1.17.2_devstral-2512 | 0.5380 | 0.6760 |
| 20250726_mini-v1.0.0_gemini-2.5-pro | 0.5360 | 0.2884 |
| 20250726_mini-v1.0.0_o4-mini-2025-04-16 | 0.4500 | 0.2100 |
| 20250807_mini-v1.7.0_kimi-k2-instruct | 0.4380 | 0.5316 |
| 20250807_mini-v1.7.0_gpt-5-nano | 0.3480 | 0.0381 |
| 20250807_mini-v1.7.0_gpt-oss-120b | 0.2600 | 0.0571 |
| 20250720_mini-v0.0.0-Llama-4-Maverick-17B-Instruct | 0.2100 | 0.3137 |
| 20250803_mini-v1.0.0_qwen2-5-coder-32b-instruct | 0.0900 | 0.0681 |

Two-system cascades on step count (threshold fitted on half the items, scored on the other half; post hoc):

| cheap | strong | threshold steps | escalated | cascade acc | cascade usd | cheap acc | cheap usd | strong acc | strong usd |
|---|---|---|---|---|---|---|---|---|---|
| 20260217_mini-v2.0.0_minimax-2-5-high | 20260217_mini-v2.0.0_claude-4-5-opus-high | 250.0000 | 0.0000 | 0.7320 | 0.0753 | 0.7320 | 0.0753 | 0.7600 | 0.7674 |
| 20260217_mini-v2.0.0_gemini-3-flash-high | 20260217_mini-v2.0.0_claude-4-5-opus-high | 159.0000 | 0.0000 | 0.7280 | 0.3596 | 0.7280 | 0.3596 | 0.7600 | 0.7674 |
