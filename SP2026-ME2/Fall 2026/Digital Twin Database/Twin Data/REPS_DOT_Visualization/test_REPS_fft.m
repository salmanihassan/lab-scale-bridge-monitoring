function test_REPS_fft()
% Mathematical checks exercise scaling, Nyquist handling, and gap rejection.
fs=100; N=1000; t=(0:N-1)'/fs;
% Bin-centered cosine, known offset and trend: recovered amplitude must be 0.2 g.
z=.9+.003*t+.2*cos(2*pi*8*t);
[s,r]=REPS_fft_interval(t,z); assert(s.valid,r); [~,k]=min(abs(s.f-8));
assert(abs(s.amplitude(k)-.2)<1e-6,'Hann coherent-gain amplitude error.');
assert(s.N==N && abs(s.df-.1)<1e-9 && abs(s.peakHz-8)<1e-9);
% Odd length uses doubling of its last positive-frequency bin as well.
[o,~]=REPS_fft_interval(t(1:999),.2*cos(2*pi*(80*fs/999)*t(1:999)));
assert(o.valid); assert(abs(o.amplitude(81)-.2)<1e-6);
% Regular missing acquisition breaks never get bridged to obtain a spectrum.
tg=t; tg=tg+.1*floor((0:N-1)'/90);
[bad,~]=REPS_fft_interval(tg,z); assert(~bad.valid && bad.duration<4);
z(100:100:end)=NaN; [bad,~]=REPS_fft_interval(t,z); assert(~bad.valid);
fprintf('FFT mathematical scaling and gap-rejection checks passed.\n');
end
