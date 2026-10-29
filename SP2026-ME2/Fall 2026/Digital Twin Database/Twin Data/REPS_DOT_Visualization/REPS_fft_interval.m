function [s,reason]=REPS_fft_interval(t,z)
%REPS_FFT_INTERVAL Base-MATLAB FFT; retains the original continuity criteria.
% Periodic Hann window is evaluated from its definition, not a toolbox call.
dt=diff(t); md=median(dt(dt>0)); valid=isfinite(z)&isfinite(t);
split=[true;dt<=0 | dt>1.5*md | ~valid(1:end-1) | ~valid(2:end)];
a=find(split); b=[a(2:end)-1;numel(t)]; durations=t(b)-t(a); durations(~valid(a))=-Inf;
[len,j]=max(durations); if ~isfinite(len), len=0; j=1; end
ix=a(j):b(j); tt=t(ix); zz=z(ix); localdt=diff(tt);
s=struct('valid',false,'duration',len,'fs',NaN,'start',tt(1),'stop',tt(end),'jitter',NaN, ...
    'N',NaN,'df',NaN,'gridSpan',NaN,'sourceN',numel(ix),'peakHz',NaN,'peakAmplitude',NaN);
if numel(tt)>1, s.fs=1/median(localdt); s.jitter=max(abs(localdt-median(localdt)))/median(localdt); end
if any(dt<=0), reason="Nonincreasing timestamps"; return; end
if len<4 || numel(ix)<256, reason="Continuous interval below 4 s / 256 samples"; return; end
if s.jitter>.20, reason="Within-interval jitter exceeds 20 percent"; return; end
grid=(tt(1):1/s.fs:tt(end))';
x=interp1(tt,zz,grid,'linear'); % No extrapolation or interpolation across rejected gaps.
assert(all(isfinite(x)) && grid(1)>=tt(1) && grid(end)<=tt(end));
x=detrend(x,1); N=numel(x); w=.5-.5*cos(2*pi*(0:N-1)'/N);
Y=abs(fft(x.*w))/sum(w); L=floor(N/2)+1;
s.amplitude=Y(1:L);
if rem(N,2)==0, s.amplitude(2:end-1)=2*s.amplitude(2:end-1); else, s.amplitude(2:end)=2*s.amplitude(2:end); end
s.f=(0:L-1)'*s.fs/N; s.N=N; s.df=s.fs/N; s.gridSpan=grid(end)-grid(1);
s.t=grid; s.residual=x; s.window=w;
band=s.f>=.5 & s.f<=min(40,.4*s.fs); indices=find(band);
[s.peakAmplitude,k]=max(s.amplitude(band)); s.peakHz=s.f(indices(k));
s.valid=true; reason="Accepted: base MATLAB FFT";
end
