"""Independent delivery audit. Optional: Python + numpy/pandas/Pillow.

Uses the initial source-byte snapshot, not just the MATLAB before/after pair.
Recomputes acceleration metrics independently with NumPy least squares.
"""
from pathlib import Path
import csv, hashlib, json, re, zipfile
import numpy as np
import pandas as pd
from PIL import Image, ImageOps, ImageDraw

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
initial = json.loads((OUT/'input_hashes_before.json').read_text())
current = {str(p.relative_to(ROOT/'cleaned_data')).replace('\\','/'):sha(p)
           for p in sorted((ROOT/'cleaned_data').rglob('*')) if p.is_file()}
assert initial == current, 'A source file changed since initial audit'
M = pd.read_csv(OUT/'run_metrics.csv')
M.spectral_eligible=M.spectral_eligible.astype(bool)
P = pd.read_csv(OUT/'plot_manifest.csv')
assert M.run_id.is_unique and P.figure_id.is_unique and P.figure_filename.is_unique
assert P.experimental_conditions.notna().all()
assert P.experimental_conditions.str.len().gt(10).all()
static=M[M.category=='Static load']
groups=static.groupby(['source_subfolder','load_kg','load_position_norm','vibration_pwm'],dropna=False).ngroups
repeatability=P.loc[P.figure_filename.str.contains('static_repeatability'),'original_numerical_findings'].iloc[0]
assert f'form {groups} batch/mass/position groups' in repeatability
def permitted(path):
    return not any(x in {'9_4_26','911_data'} for x in path.replace('\\','/').split('/'))
assert all(permitted(p) for p in M.run_id)
assert set(M.qc_status) == {'CHECK'}
assert M.loc[M.category=='Thermal',['load_kg','load_position_norm','vibration_pwm','commanded_frequency_Hz']].isna().all().all()
source_set = set('cleaned_data/'+p for p in M.run_id)
for _,r in P.iterrows():
    sources=r.source_cleaned_csv_files.split('; ')
    assert len(sources)==r.source_count
    for s in sources:
        assert permitted(s) and s in source_set and (ROOT/s).is_file()
    exported=OUT/r.figure_filename
    copied=OUT/'report'/'figures'/r.report_filename
    assert sha(exported)==sha(copied)
    with Image.open(exported) as im:
        assert im.width>=2000 and im.height>=1000, 'Unexpected low-resolution export'
        assert abs(im.info.get('dpi',(300,300))[0]-300)<1
tex=(OUT/'report'/'main.tex').read_text(encoding='utf-8')
refs=re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}',tex)
assert len(refs)==len(P) and len(refs)==len(set(refs))
assert all((OUT/'report'/r).is_file() for r in refs)
assert 'not present a completed, trained, or validated AI digital twin' in tex
assert tex.count('\\section{')==14
for _,r in M.iterrows():
    d=pd.read_csv(ROOT/'cleaned_data'/r.run_id)
    x=d.time_s.to_numpy(); y=d.accel_z_g.to_numpy(); ok=np.isfinite(x)&np.isfinite(y)
    design=np.column_stack([np.ones(ok.sum()),x[ok]-x[ok].mean()])
    residual=y[ok]-design@np.linalg.lstsq(design,y[ok],rcond=None)[0]
    assert np.isclose(np.sqrt(np.mean(residual**2)),r.rms_z_g,rtol=1e-10,atol=1e-12)
    assert np.isclose(np.max(np.abs(residual)),r.peak_z_g,rtol=1e-10,atol=1e-12)
    assert np.isclose(d.loadcell_left_raw.median(),r.lc_left_median)
    assert np.isclose(d.loadcell_right_raw.median(),r.lc_right_median)
assert M.spectral_eligible.sum()==1 and M.loc[M.spectral_eligible,'test_id'].iloc[0]=='T0236'
assert M.loc[~M.spectral_eligible,['dominant_Hz','fft_peak_g']].isna().all().all()
assert (M.loc[M.spectral_reason.str.contains('below 4'),'longest_interval_s']<4).all()
assert (M.loc[M.longest_interval_s>=4,'spectral_reason']=='Accepted: base MATLAB FFT').all()
# Independent reconstruction of the actual accepted interval and its FFT bins.
r=M.loc[M.spectral_eligible].iloc[0]
d=pd.read_csv(ROOT/'cleaned_data'/r.run_id)
seg=d[d.time_s.between(r.spectral_start_s,r.spectral_end_s)]
dt=np.diff(seg.time_s); fs=1/np.median(dt)
assert len(seg)==741 and np.max(np.abs(dt-np.median(dt)))/np.median(dt)<=.20
assert np.max(dt)<=1.5*np.median(np.diff(d.time_s))
grid=r.spectral_start_s+np.arange(int(np.floor((r.spectral_end_s-r.spectral_start_s)*fs))+1)/fs
assert len(grid)==740 and grid[-1]<=r.spectral_end_s
y=np.interp(grid,seg.time_s,seg.accel_z_g)
A=np.column_stack([np.ones(len(y)),np.arange(len(y))])
y=y-A@np.linalg.lstsq(A,y,rcond=None)[0]
w=.5-.5*np.cos(2*np.pi*np.arange(len(y))/len(y))
amp=np.abs(np.fft.rfft(y*w))/w.sum(); amp[1:-1]*=2
freq=np.fft.rfftfreq(len(y),1/fs)
F=pd.read_csv(OUT/'T0236_fft_spectrum.csv')
assert np.allclose(freq,F.frequency_Hz,rtol=1e-10,atol=1e-10)
assert np.allclose(amp,F.amplitude_g,rtol=1e-8,atol=1e-12)
assert np.isclose(r.fft_df_Hz,fs/len(y))
band=np.flatnonzero((freq>=.5)&(freq<=min(40,.4*fs))); peak=band[np.argmax(amp[band])]
assert np.isclose(r.dominant_Hz,freq[peak]) and np.isclose(r.fft_peak_g,amp[peak])
# Original verified metrics must survive the surgical revision unchanged.
old=pd.read_csv(OUT/'validation'/'revision_baseline'/'run_metrics.csv')
allowed={'spectral_eligible','spectral_reason','dominant_Hz','fft_peak_g','analysis_notes'}
for col in old.columns:
    if col in allowed: continue
    pd.testing.assert_series_equal(old[col],M[col],check_dtype=False,check_exact=True)
baseline=pd.read_csv(OUT/'validation'/'revision_baseline'/'figure_hashes.csv')
now={Path(r.figure_filename).name:sha(OUT/r.figure_filename).upper() for _,r in P.iterrows()}
changed=[r.filename for _,r in baseline.iterrows() if now.get(r.filename)!=r.sha256]
assert {int(x[1:3]) for x in changed}=={5,6,8,9,17,18,19,21,23,24,30}
assert len(now)==33 and set(baseline.filename)<=set(now)
words=P.engineering_analysis.str.split().str.len()
assert words.ge(40).all() and words.le(155).all()
experimental=~P.figure_id.isin(['F01','F02','F03','F04','F16','F17','F31','F32'])
assert words[experimental].ge(80).all()
E=pd.read_csv(OUT/'analysis_evidence.csv')
assert E.value.notna().all() and set(E.figure_id)==set(P.figure_id)
with zipfile.ZipFile(OUT/'REPS_DOT_Overleaf.zip') as z:
    assert {'main.tex','plot_manifest.csv','dataset_index.csv','frequency_audit.csv'}<=set(z.namelist())
    assert set(refs)<set(z.namelist())
    assert z.read('main.tex')==(OUT/'report'/'main.tex').read_bytes()
    for r in refs: assert z.read(r)==(OUT/'report'/r).read_bytes()

# Contact sheets support inspection of every figure without altering exports.
paths=[OUT/p for p in P.figure_filename]
for start in range(0,len(paths),8):
    sheet=Image.new('RGB',(1800,1440),'#e6e9ed'); draw=ImageDraw.Draw(sheet)
    for j,p in enumerate(paths[start:start+8]):
        im=Image.open(p).convert('RGB'); im.thumbnail((880,320))
        x=(j%2)*900+(900-im.width)//2; y=(j//2)*360+28
        sheet.paste(im,(x,y)); draw.text(((j%2)*900+12,(j//2)*360+6),p.name,fill='black')
    sheet.save(OUT/'validation'/f'figure_contact_{start//8+1}.png')
result={'initial_source_hashes_unchanged':True,'source_files_hashed':len(current),
        'recordings_verified':len(M),'figures_verified':len(P),
        'independent_rms_peak_median_checks':'passed for all recordings',
        'figure_copy_hashes':'identical','report_references':'all valid',
        'overleaf_archive':'complete and image-identical','base_fft':'T0236 bins independently reproduced with NumPy',
        'original_verified_metrics':'unchanged','original_figures_retained':32,
        'figures_revised':len(changed),'figures_unchanged':32-len(changed),'figures_added':1,'figures_removed':0,
        'discussion_word_range':[int(words.min()),int(words.max())],
        'thermal_unknown_metadata':'preserved','excluded_source_paths':0,
        'static_repetition_groups':groups,'figure_conditions':'all populated with explicit unknown labels'}
(OUT/'validation'/'independent_validation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
