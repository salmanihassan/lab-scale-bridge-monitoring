% -------------------------------------------------------------------------
% Temperature-Aware Digital Twin Model
%
% Week 7: Environmental Compensation
%
% This script:
% 1. Generates dummy baseline data with temperature-induced sensor drift
% 2. Models measured load response as a function of applied load and temperature
% 3. Compares an uncorrected static model against a temperature-aware model
% 4. Computes residuals before and after compensation
% 5. Shows how temperature compensation reduces false alarms
%
% Purpose:
% Prevent the digital twin from flagging normal thermal drift as structural
% damage or abnormal behavior.
% -------------------------------------------------------------------------

clc;
clear;
close all;

%% Settings

rng(7);

dt = 0.1;                    % sampling interval [s]
tEnd = 120;                  % total test duration [s]
t = (0:dt:tEnd)';            % time vector
N = length(t);

kTol = 2;                    % tolerance multiplier

%% Generate dummy applied load profile

% Constant applied load with a few small step changes
AppliedLoad = 10 * ones(N,1);

AppliedLoad(t > 35 & t <= 70) = 12;
AppliedLoad(t > 70 & t <= 95) = 8;
AppliedLoad(t > 95) = 10;

%% Generate dummy temperature profile

% Temperature slowly rises during the test, then partially cools
Temp = 22 + 0.08*t - 0.003*max(t-75,0).^2;

% Add small temperature sensor noise
Temp = Temp + 0.08*randn(N,1);

Tref = 22;                   % reference calibration temperature [deg C]

%% Generate measured load response with temperature drift

% True structural response coefficients
trueSlope = 1.00;
trueIntercept = 0.10;

% Temperature drift coefficient
% This means the load cell reading drifts by 0.08 load units per deg C
tempCoeff = 0.08;

% Random measurement noise
noise = 0.20 * randn(N,1);

% Measured sensor response includes true load + thermal drift + noise
MeasuredLoad = trueSlope*AppliedLoad ...
             + trueIntercept ...
             + tempCoeff*(Temp - Tref) ...
             + noise;

%% Uncorrected static twin model

% This model ignores temperature and assumes measured load depends only on load
pStatic = polyfit(AppliedLoad, MeasuredLoad, 1);

Expected_Static = polyval(pStatic, AppliedLoad);

Residual_Static = MeasuredLoad - Expected_Static;

sigmaStatic = std(Residual_Static);
tolStatic = kTol * sigmaStatic;

%% Temperature-aware twin model

% Regression matrix:
% MeasuredLoad = b0 + b1*AppliedLoad + b2*(Temp - Tref)
X = [ones(N,1), AppliedLoad, Temp - Tref];

beta = X \ MeasuredLoad;

b0 = beta(1);
bLoad = beta(2);
bTemp = beta(3);

Expected_TempAware = X * beta;

Residual_TempAware = MeasuredLoad - Expected_TempAware;

sigmaTempAware = std(Residual_TempAware);
tolTempAware = kTol * sigmaTempAware;

%% Temperature-corrected measurement

% Remove learned temperature drift from measured signal
MeasuredLoad_Corrected = MeasuredLoad - bTemp*(Temp - Tref);

%% False alarm comparison

falseAlarm_Static = abs(Residual_Static) > tolStatic;
falseAlarm_TempAware = abs(Residual_TempAware) > tolTempAware;

falseAlarmRate_Static = 100 * sum(falseAlarm_Static) / N;
falseAlarmRate_TempAware = 100 * sum(falseAlarm_TempAware) / N;

%% Print results

fprintf('\n');
fprintf('----------------------------------------------\n');
fprintf('Temperature-Aware Digital Twin Results\n');
fprintf('----------------------------------------------\n\n');

fprintf('Uncorrected Static Model:\n');
fprintf('    Residual Std Dev       = %.4f\n', sigmaStatic);
fprintf('    Tolerance Band         = +/- %.4f\n', tolStatic);
fprintf('    False Alarm Rate       = %.2f %%\n\n', falseAlarmRate_Static);

fprintf('Temperature-Aware Model:\n');
fprintf('    Intercept              = %.4f\n', b0);
fprintf('    Load Coefficient       = %.4f\n', bLoad);
fprintf('    Temperature Coeff.     = %.4f per deg C\n', bTemp);
fprintf('    Residual Std Dev       = %.4f\n', sigmaTempAware);
fprintf('    Tolerance Band         = +/- %.4f\n', tolTempAware);
fprintf('    False Alarm Rate       = %.2f %%\n\n', falseAlarmRate_TempAware);

fprintf('Improvement:\n');
fprintf('    Residual Std Reduction = %.2f %%\n', ...
    100*(1 - sigmaTempAware/sigmaStatic));

fprintf('\n');

%% Plot results

figure('Name','Temperature Compensation Study', ...
       'NumberTitle','off', ...
       'Color','w', ...
       'Units','normalized', ...
       'Position',[0.06 0.08 0.88 0.80]);

tiledlayout(3,2,'TileSpacing','compact','Padding','compact');

%% Plot 1: Applied load
nexttile;
plot(t, AppliedLoad, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Applied Load', 'FontWeight','bold');
title('Applied Load Profile', 'FontWeight','bold');

%% Plot 2: Temperature profile
nexttile;
plot(t, Temp, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Temperature (^{\circ}C)', 'FontWeight','bold');
title('Temperature Drift During Test', 'FontWeight','bold');

%% Plot 3: Measured load before/after compensation
nexttile;
plot(t, MeasuredLoad, 'LineWidth', 1.4);
hold on;
plot(t, MeasuredLoad_Corrected, 'LineWidth', 1.4);
plot(t, AppliedLoad, '--', 'LineWidth', 1.4);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Load Reading', 'FontWeight','bold');
title('Raw vs Temperature-Corrected Load', 'FontWeight','bold');
legend('Raw Measured Load', ...
       'Temperature-Corrected Load', ...
       'Applied Load', ...
       'Location','best');

%% Plot 4: Expected response comparison
nexttile;
plot(t, MeasuredLoad, 'LineWidth', 1.2);
hold on;
plot(t, Expected_Static, '--', 'LineWidth', 1.6);
plot(t, Expected_TempAware, 'LineWidth', 1.6);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Load Response', 'FontWeight','bold');
title('Static Twin vs Temperature-Aware Twin', 'FontWeight','bold');
legend('Measured Load', ...
       'Static Expected Response', ...
       'Temperature-Aware Expected Response', ...
       'Location','best');

%% Plot 5: Residuals before compensation
nexttile;
plot(t, Residual_Static, 'LineWidth', 1.3);
hold on;
yline(tolStatic, '--', 'LineWidth', 1.4);
yline(-tolStatic, '--', 'LineWidth', 1.4);
yline(0, 'LineWidth', 1.2);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Residual', 'FontWeight','bold');
title('Residuals Without Temperature Compensation', 'FontWeight','bold');
legend('Residual', ...
       'Upper Limit', ...
       'Lower Limit', ...
       'Zero Line', ...
       'Location','best');

%% Plot 6: Residuals after compensation
nexttile;
plot(t, Residual_TempAware, 'LineWidth', 1.3);
hold on;
yline(tolTempAware, '--', 'LineWidth', 1.4);
yline(-tolTempAware, '--', 'LineWidth', 1.4);
yline(0, 'LineWidth', 1.2);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Residual', 'FontWeight','bold');
title('Residuals With Temperature Compensation', 'FontWeight','bold');
legend('Residual', ...
       'Upper Limit', ...
       'Lower Limit', ...
       'Zero Line', ...
       'Location','best');

sgtitle('Environmental Compensation for Temperature-Aware Digital Twin', ...
        'FontWeight','bold', ...
        'FontSize', 14);

%% Optional second figure: residual distribution comparison

figure('Name','Residual Distribution Comparison', ...
       'NumberTitle','off', ...
       'Color','w', ...
       'Units','normalized', ...
       'Position',[0.18 0.18 0.64 0.42]);

histogram(Residual_Static, 25, 'Normalization','pdf');
hold on;
histogram(Residual_TempAware, 25, 'Normalization','pdf');

grid on;
box on;
xlabel('Residual', 'FontWeight','bold');
ylabel('Probability Density', 'FontWeight','bold');
title('Residual Distribution Before and After Temperature Compensation', ...
      'FontWeight','bold');

legend('Without Temperature Compensation', ...
       'With Temperature Compensation', ...
       'Location','best');