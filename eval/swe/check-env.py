from pathlib import Path

for line in Path(".env").read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k, v = s.split("=", 1)
    k, v = k.strip(), v.strip().strip('"').strip("'")
    sens = "KEY" in k.upper() or "TOKEN" in k.upper()
    if sens:
        print(f"{k}={'SET len=' + str(len(v)) if v else 'EMPTY'}")
    else:
        print(f"{k}={v if v else 'EMPTY'}")
