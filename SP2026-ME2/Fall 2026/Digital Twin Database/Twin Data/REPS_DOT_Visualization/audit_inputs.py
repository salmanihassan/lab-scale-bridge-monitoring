"""Read-only inventory and SHA-256 baseline; never reads raw sensor workbooks."""
from pathlib import Path
import hashlib, json, collections
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'REPS_DOT_Visualization'
CLEAN = ROOT / 'cleaned_data'
excluded = {'9_4_26', '911_data'}
hashes = {str(p.relative_to(CLEAN)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(CLEAN.rglob('*')) if p.is_file()}
(OUT / 'input_hashes_before.json').write_text(json.dumps(hashes, indent=2))
F = pd.read_csv(CLEAN / 'ME2_master_features.csv')
Q = pd.read_csv(CLEAN / 'ME2_QC_report.csv')
rows=[]
for _, r in F.iterrows():
    batch = str(r.source_subfolder) if pd.notna(r.source_subfolder) else 'thermal_transient'
    if batch in excluded: continue
    stem=Path(r.filename).stem
    if stem.endswith('.csv'): stem=stem[:-4]
    if batch=='thermal_transient': stem=r.test_id
    p=CLEAN / batch / (stem+'_clean.csv')
    if not p.exists(): print('MISSING', p); continue
    d=pd.read_csv(p); t=d.time_s.to_numpy(); dt=np.diff(t); med=np.median(dt[dt>0])
    motor=d.motor_state.fillna('').astype(str).to_numpy()
    valid=np.isfinite(d.accel_z_g.to_numpy())
    breaks=np.r_[True, (dt<=0)|(dt>1.5*med)|(~valid[:-1])|(~valid[1:])]
    starts=np.flatnonzero(breaks); ends=np.r_[starts[1:],len(t)]
    runs=[(t[b-1]-t[a],b-a,a,b) for a,b in zip(starts,ends) if valid[a]]
    best=max(runs, default=(0,0,0,0))
    q=Q[(Q.filename==r.filename)&(Q.source_subfolder.fillna('')==str(r.source_subfolder if pd.notna(r.source_subfolder) else ''))]
    rows.append(dict(id=r.test_id,batch=batch,file=str(p.relative_to(ROOT)),n=len(t),dt=med,
       dt_cv=np.std(dt)/np.mean(dt),gap_count=int(np.sum(dt>1.5*med)),maxgap=max(dt),
       best_s=best[0],best_n=best[1],best_start=best[2],best_end=best[3],
       span=t[-1]-t[0],on=int(np.sum(motor=='ON')),off=int(np.sum(motor=='OFF')),
       z_missing=d.accel_z_g.isna().mean(),lcL_min=d.loadcell_left_raw.min(),lcL_max=d.loadcell_left_raw.max(),
       lcR_min=d.loadcell_right_raw.min(),lcR_max=d.loadcell_right_raw.max(),
       qc=q.qc_status.iloc[0] if len(q) else 'UNKNOWN'))
A=pd.DataFrame(rows); A.to_csv(OUT/'input_audit.csv',index=False)
print('Manifest exists:', (CLEAN/'model_dataset'/'manifest.csv').exists())
print(A.groupby('batch').agg(runs=('id','size'),min_span=('span','min'),max_span=('span','max'),min_segment=('best_s','min'),max_segment=('best_s','max'),missing_z=('z_missing','max')).to_string())
print('QC', A.qc.value_counts().to_dict())
print(A[A.batch=='thermal_transient'].to_string(index=False))
print('Largest left outputs', A.nlargest(5,'lcL_max')[['id','batch','lcL_max']].to_string(index=False))
print('Longest intervals', A.nlargest(8,'best_s')[['id','batch','best_s','on','off']].to_string(index=False))
