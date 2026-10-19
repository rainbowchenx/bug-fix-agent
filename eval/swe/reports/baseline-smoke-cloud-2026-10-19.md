# SWE Baseline Smoke (cloud)

- **commit**: `ba6d6e1410d26cb1d9c364e20d6f6cfaa806c2ee`
- **model**: `deepseek-flash` @ `https://api.deepseek.com/anthropic`
- **dataset**: lite-smoke-10
- **pipeline fixed**: **6/10** (0.6)
- **predictions.jsonl**: 6 rows
- **finished**: 2026-10-19T14:16:50.746869+00:00

| instance | outcome | reason | patch lines |
|---|---|---|---|
| `pallets__flask-4992` | fixed |  | 88 |
| `psf__requests-863` | fixed |  | 59 |
| `mwaskom__seaborn-3407` | fixed |  | 52 |
| `pydata__xarray-4094` | unfixed | analyze_failed | 0 |
| `astropy__astropy-14182` | unfixed | implement_failed | 0 |
| `pytest-dev__pytest-8906` | fixed |  | 34 |
| `scikit-learn__scikit-learn-10297` | fixed |  | 66 |
| `matplotlib__matplotlib-24970` | fixed |  | 61 |
| `django__django-12708` | unfixed | implement_failed | 0 |
| `sympy__sympy-14024` | unfixed | implement_failed | 0 |

## Unfixed details
### `pydata__xarray-4094` — `analyze_failed`
```
Analyze failed: Claude Code returned an error result: Reached maximum number of turns (25)
```

### `astropy__astropy-14182` — `implement_failed`
```
Claude Code returned an error result: Reached maximum number of turns (40)
```

### `django__django-12708` — `implement_failed`
```
Reproduction step failed: Claude Code returned an error result: Reached maximum number of turns (40)
```

### `sympy__sympy-14024` — `implement_failed`
```
Claude Code returned an error result: Reached maximum number of turns (40)
```

