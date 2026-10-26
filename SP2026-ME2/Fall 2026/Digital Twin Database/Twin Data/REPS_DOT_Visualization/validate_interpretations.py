"""Independent sample/aggregate checks supporting the revised engineering prose."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

O=Path(__file__).resolve().parent
M=pd.read_csv(O/'run_metrics.csv')
E=pd.read_csv(O/'analysis_evidence.csv').set_index(['figure_id','metric']).value
checked=set()
def check(fig,key,value):
    pair=(f'F{fig:02}',key)
    assert np.isclose(E.loc[pair],value,rtol=1e-8,atol=1e-10),(pair,E.loc[pair],value)
    checked.add(pair)
def series(fig,values):
    keys=E.loc[f'F{fig:02}'].index
    assert len(keys)==len(values)
    for k,v in zip(keys,values): check(fig,k,v)
def raw(row): return pd.read_csv(O.parent/'cleaned_data'/row.run_id)
def residual(d,axis='z'):
    y=d[f'accel_{axis}_g'].to_numpy(); t=d.time_s.to_numpy(); ok=np.isfinite(y)&np.isfinite(t)
    x=np.column_stack([np.ones(ok.sum()),t[ok]-t[ok].mean()])
    z=np.full(len(t),np.nan);z[ok]=y[ok]-x@np.linalg.lstsq(x,y[ok],rcond=None)[0]
    return z
for _,r in M.iterrows():
    d=raw(r)
    for axis in 'xyz':
        z=residual(d,axis)
        assert np.isclose(np.sqrt(np.nanmean(z*z)),r[f'rms_{axis}_g'],rtol=1e-9,atol=1e-12)
        if axis=='z': assert np.isclose(np.nanmax(abs(z)),r.peak_z_g,rtol=1e-9,atol=1e-12)

V=M[M.category=='Vibration']; C=M[M.category=='Load + vibration']; ST=M[M.category=='Static load']
TH=M[M.category=='Thermal']; T=M.set_index('test_id'); t236=T.loc['T0236']; t2=T.loc['THERMAL_01_PART2']
candidates=M[M.category.isin(['Vibration','Frequency sweep','Load + vibration','Wind','Impact'])]
series(1,[len(C),len(M),100*len(C)/len(M),len(ST),len(V)])
series(2,[M[['load_kg','vibration_pwm']].notna().all(axis=1).sum(),len(TH),(M.vibration_pwm==192).sum(),(M.vibration_pwm==64).sum()])
series(3,[M.median_fs_Hz.median(),M.effective_fs_Hz.median(),t2.duration_s,t2.valid_span_s])
series(4,[len(raw(t236)),(M.qc_status=='CHECK').sum()])
series(5,[T.loc['T0168','lc_left_median'],T.loc['T0173','lc_left_median'],np.ptp(raw(T.loc['T0173']).loadcell_right_raw)])
S=ST[ST.source_subfolder=='918 load variation'].groupby(['load_kg','load_position_norm'])
L=S.lc_left_median.mean().unstack().to_numpy(); R=S.lc_right_median.mean().unstack().to_numpy()
LS=S.lc_left_median.std().unstack().to_numpy(); RS=S.lc_right_median.std().unstack().to_numpy()
pct=lambda a,b:100*(b/a-1)
series(6,[pct(L[0,0],L[1,0]),pct(L[0,1],L[1,1]),pct(L[0,2],L[1,2]),pct(R[0,0],R[1,0]),pct(R[0,2],R[1,2])])
A=L-R; diff=A[1]-A[0];series(7,[diff[0],-diff[1],-diff[2]])
cv=np.r_[LS.ravel()/L.ravel(),RS.ravel()/R.ravel()]*100
series(8,[cv.min(),cv.max(),RS[1,2],RS[0,2]])
series(9,[L[1,0],L[1,2],-pct(L[1,0],L[1,2]),R[1,0],R[1,2],pct(R[1,0],R[1,2])])
series(10,A[1])
ratio=S.raw_left_share.mean().unstack().to_numpy();series(11,[*ratio[1],ratio[0,0],ratio[0,2]])
P=pd.read_csv(O/'plot_manifest.csv').set_index('figure_id')
def sources(fig):
    paths=P.loc[f'F{fig:02}','source_cleaned_csv_files'].split('; ')
    return M[M.run_id.isin([p.removeprefix('cleaned_data/') for p in paths])]
series(12,sources(12).sort_values('vibration_pwm').rms_z_g)
vg=V.groupby('vibration_pwm'); vr=vg[['rms_x_g','rms_y_g','rms_z_g']].mean().to_numpy()
vp=vg.peak_z_g.mean().to_numpy(); vs=vg.rms_z_g.std().to_numpy(); ps=vg.peak_z_g.std().to_numpy()
series(13,[*vr[:,2],pct(vr[0,2],vr[1,2]),pct(vr[1,2],vr[2,2]),pct(vr[0,2],vr[2,2]),vs[0]])
series(14,[*vp,-pct(vp[1],vp[2]),ps[0],ps[1]])
series(15,[*vr[2],pct(vr[2,2],vr[2,1]),vr[0,2]/vr[0,0],*(vr[2]/vr[0])])
series(16,[candidates.spectral_eligible.sum(),len(candidates),t236.longest_interval_s,candidates[candidates.test_id!='T0236'].longest_interval_s.max()])
series(17,[len(candidates)-candidates.spectral_eligible.sum(),candidates.spectral_eligible.sum()])
cg=C.groupby(['load_kg','load_position_norm','vibration_pwm']).rms_z_g.mean()
a,b,c=[cg.loc[m,.25,64] for m in [.25,.5,1]]
series(18,[a,b,c,-pct(a,b),pct(b,c),-pct(cg.loc[.25,.5,192],cg.loc[1,.5,192])])
cells=cg.unstack('load_position_norm'); count=((cells[.5]<cells[.25])&(cells[.5]<cells[.75])).sum()
a,b,c=[cg.loc[.5,p,128] for p in [.25,.5,.75]];series(19,[count,a,b,c,-pct(a,b),-pct(c,b)])
q=sources(20);ll=q[q.load_position_norm==.25].lc_left_median;rr=q[q.load_position_norm==.75].lc_left_median
series(20,[rr.iloc[0],ll.min(),ll.max()])
off=ST[(ST.source_subfolder=='9_25_loadvib')&(ST.load_kg==.25)].groupby('load_position_norm').rms_z_g
on=C[(C.load_kg==.25)&(C.vibration_pwm==192)].groupby('load_position_norm').rms_z_g.mean()
series(21,[*pct(off.mean().to_numpy(),on.to_numpy()),off.std().loc[.25],off.mean().loc[.5],on.loc[.5]])

# Reconstruct paired one-second summaries directly from the cleaned samples.
names=['temp_left_C','temp_center_C','temp_right_C','loadcell_left_raw','loadcell_right_raw','accel_x_g','accel_y_g','accel_z_g']
deltas=[]; slopes=[]; r2s=[]
fits=pd.read_csv(O/'thermal_fits.csv')
for _,r in TH.iterrows():
    d=raw(r);d=d[d[names].notna().any(axis=1)&d.time_s.notna()].copy()
    d['bin']=np.floor(d.time_s-d.time_s.min())
    b=pd.DataFrame({n:d.loc[d[n].notna()&d.temp_left_C.notna()].groupby('bin')[n].median() for n in names})
    deltas.append((b.loc[b.index>=b.index.max()-5].median()-b.loc[b.index<=b.index.min()+5].median()).to_numpy())
    ss=[];rs=[]
    for n in names[3:]:
        q=b[['temp_left_C',n]].dropna();x=q.temp_left_C.to_numpy();y=q[n].to_numpy()
        G=np.column_stack([np.ones(len(x)),x-x.mean()]);coef=np.linalg.lstsq(G,y,rcond=None)[0]
        r2=1-np.sum((y-G@coef)**2)/np.sum((y-y.mean())**2);ss.append(coef[1]);rs.append(r2)
        original=fits[(fits.segment==r.test_id)&(fits.sensor==n)].iloc[0]
        assert np.isclose(coef[1],original.slope_per_C,rtol=1e-8,atol=1e-10)
        assert np.isclose(r2,original.r_squared,atol=1e-10)
    slopes.append(ss);r2s.append(rs)
delta=np.array(deltas);sl=np.array(slopes);r2=np.array(r2s)
series(22,delta[:,:3].ravel())
series(23,[sl[1,1],r2[1,1],sl[0,1],r2[0,1],sl[0,0],r2[0,0],sl[1,0],r2[1,0]])
series(24,[sl[0,2],sl[1,2],r2[0,2],r2[1,2],sl[0,4],sl[1,4],r2[0,4],r2[1,3]])
series(25,delta[:,3:5].ravel())
series(26,[sl[1,1]/sl[0,1],r2[0,1],r2[1,1],abs(sl[0,0]/sl[1,0]),r2[0,0]])
q=sources(27)
series(27,[q[(q.category=='Wind')&(q.vibration_pwm==0)].peak_z_g.iloc[0],q[q.category=='Impact'].peak_z_g.iloc[0],q[(q.category=='Wind')&(q.vibration_pwm==192)].peak_z_g.iloc[0]])
im=M[M.category=='Impact'];wi=M[M.category=='Wind'].set_index('test_id');imidx=im.set_index('test_id')
series(28,[im.peak_z_g.min(),im.peak_z_g.max(),im.peak_z_g.max()/im.peak_z_g.min(),imidx.loc['T0258','rms_z_g'],wi.loc['T0256','rms_z_g'],wi.loc['T0256','peak_z_g'],wi.loc['T0253','rms_z_g'],wi.loc['T0254','rms_z_g']])
energy=[]
for _,r in im.sort_values('test_id').iterrows():
    d=raw(r);z=residual(d);rel=d.time_s.to_numpy()-d.time_s.iloc[np.nanargmax(abs(z))]
    energy.append(100*np.nansum(z[abs(rel)<=1]**2)/np.nansum(z*z))
    bins=pd.DataFrame({'bin':np.floor(rel),'z2':z*z}).groupby('bin').z2.mean().pow(.5)
    centers=bins.index+.5
    pre=bins[(centers>=-5)&(centers<-1)].median();post=bins[(centers>1)&(centers<=5)].median()
series(29,[*energy,pre,post])
lo=cg.idxmin();hi=cg.idxmax();series(30,[cg.min(),*lo,cg.max(),*hi,cg.max()/cg.min()])
series(31,[len(cg),len(M[M.load_kg.notna()&M.vibration_pwm.notna()&~M.category.isin(['Wind','Impact'])])])
series(32,[M.lc_extreme_count.sum(),(M.lc_extreme_count>0).sum(),t2.lc_left_max/t2.lc_left_median])
# FFT scaling and every bin are independently checked in validate_outputs.py.
d=raw(t236);seg=d[d.time_s.between(t236.spectral_start_s,t236.spectral_end_s)]
fs=1/np.median(np.diff(seg.time_s));grid=seg.time_s.iloc[0]+np.arange(int(t236.fft_N))/fs
y=np.interp(grid,seg.time_s,seg.accel_z_g);G=np.column_stack([np.ones(len(y)),np.arange(len(y))]);y-=G@np.linalg.lstsq(G,y,rcond=None)[0]
w=.5-.5*np.cos(2*np.pi*np.arange(len(y))/len(y));a=np.abs(np.fft.rfft(y*w))/sum(w);a[1:-1]*=2
f=np.fft.rfftfreq(len(y),1/fs);idx=np.flatnonzero((f>=.5)&(f<=40));order=idx[np.argsort(-a[idx])];peak,adj=order[:2];half=len(y)//2
series(33,[len(seg),len(y),fs,np.ptp(seg.time_s),fs/len(y),f[peak],a[peak],f[adj],100*(1-a[adj]/a[peak]),np.sqrt(np.mean(y[:half]**2)),np.sqrt(np.mean(y[half:]**2))])
assert checked==set(E.index)
result={'all_discussion_evidence_values_verified':len(checked),'figures':33,'all_axis_rms_and_z_peak_checks':119,'thermal_fits_independently_recomputed':10,'methods':'NumPy least squares/FFT and pandas grouped statistics from cleaned samples'}
(O/'validation'/'interpretation_validation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
