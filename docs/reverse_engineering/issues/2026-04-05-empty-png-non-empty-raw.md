# Issue: empty PNG при non-empty raw в chunk_00 (m3_0/m4_0/m11_0)

- **Дата:** 2026-04-05
- **Симптом:** часть кадров экспортируется как полностью прозрачные PNG при ненулевом размере `.bin` payload.
- **Пакеты/чанки:** `m3_0#00`, `m4_0#00`, `m11_0#00`.

## Repro

```bash
python -m tools.decode_graphics 240x320-rus-zombie-infection.jar -o .artifacts/extractor_out
python - <<'PY'
# check non-empty raw + fully transparent PNG in chunk_00
import json, os, struct, zlib

def alpha_nonzero(path):
    d=open(path,'rb').read(); i=8; idat=b''; w=h=ct=bd=None
    while i < len(d):
        ln=int.from_bytes(d[i:i+4],'big'); i+=4
        typ=d[i:i+4]; i+=4
        chunk=d[i:i+ln]; i+=ln; i+=4
        if typ==b'IHDR': w,h,bd,ct,*_=struct.unpack('>IIBBBBB',chunk)
        elif typ==b'IDAT': idat += chunk
        elif typ==b'IEND': break
    raw=zlib.decompress(idat)
    if not (ct==6 and bd==8):
        return None
    bpp=4; prev=[0]*(w*bpp); off=0; nz=0
    for _ in range(h):
        f=raw[off]; off+=1
        row=list(raw[off:off+w*bpp]); off+=w*bpp
        rec=[0]*(w*bpp)
        for x in range(w*bpp):
            a=rec[x-bpp] if x>=bpp else 0
            b=prev[x]
            c=prev[x-bpp] if x>=bpp else 0
            if f==0: r=row[x]
            elif f==1: r=(row[x]+a)&255
            elif f==2: r=(row[x]+b)&255
            elif f==3: r=(row[x]+((a+b)//2))&255
            else:
                p=a+b-c
                pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                pr=a if pa<=pb and pa<=pc else (b if pb<=pc else c)
                r=(row[x]+pr)&255
            rec[x]=r
        nz += sum(1 for x in range(3,len(rec),4) if rec[x]!=0)
        prev=rec
    return nz

for pack in ['m3_0','m4_0','m11_0']:
    frames=json.load(open(f'.artifacts/extractor_out/extracted/images/{pack}/chunk_00/frames.json'))['frames']
    bad=[]
    for f in frames:
        raw='.artifacts/extractor_out/'+f['raw_payload']
        png='.artifacts/extractor_out/'+f['path']
        if os.path.getsize(raw)>0 and alpha_nonzero(png)==0:
            bad.append(f['frame'])
    print(pack, len(bad), bad[:10])
PY
```

## Наблюдение

- Симптом воспроизводится массово, особенно в `m4_0#00`.
- Требуется проверить ветку декодера, где raw payload не пустой, но итоговая альфа полностью нулевая.
