% -------------------------------------------------------------------------
% Static Model Fit from Experimental Data
%
% This script:
% 1. Reads applied load and measured load data from an Excel file
% 2. Fits a linear model: y = a*x + b
% 3. Computes basic statistics (R^2, RMSE, residuals, tolerance)
% 4. Plots:
%    - Measured data with fitted model and tolerance band
%    - Residuals vs load
%    - Expected vs measured comparison
%
% Required Excel columns:
%   AppliedLoad, MeasuredLoad
% -------------------------------------------------------------------------

clc; clear; close all;

% fileName = 'static_baseline_data.xlsx';
% sheetName = 1;
% colApplied  = 'AppliedLoad';
% colMeasured = 'MeasuredLoad';

kTol = 2;

%% Dummy dataset
rng(1);

x = (0:2:20)';
trueSlope = 0.98;
trueIntercept = 0.12;
noiseLevel = 0.35;

y = trueSlope*x + trueIntercept + noiseLevel*randn(size(x));

%% Excel import
% tbl = readtable(fileName, 'Sheet', sheetName);
% x = tbl.(colApplied);
% y = tbl.(colMeasured);
% validIdx = ~(isnan(x) | isnan(y));
% x = x(validIdx);
% y = y(validIdx);

x = x(:);
y = y(:);

p = polyfit(x, y, 1);
a = p(1);
b = p(2);

yFit = polyval(p, x);
res  = y - yFit;

SSres  = sum(res.^2);
SStot  = sum((y - mean(y)).^2);
R2     = 1 - SSres/SStot;
RMSE   = sqrt(mean(res.^2));
muRes  = mean(res);
sigRes = std(res);
tol    = kTol * sigRes;

[xSort, idx] = sort(x);
yFitSort   = yFit(idx);
yUpperSort = yFitSort + tol;
yLowerSort = yFitSort - tol;

fprintf('\n');
fprintf('<strong>Static Model Results</strong>\n\n');

fprintf('Model:\n');
fprintf('    y = a*x + b\n\n');

fprintf('Coefficients:\n');
fprintf('    a = %.6f\n', a);
fprintf('    b = %.6f\n\n', b);

fprintf('Statistics:\n');
fprintf('    R^2           = %.6f\n', R2);
fprintf('    RMSE          = %.6f\n', RMSE);
fprintf('    Mean Residual = %.6f\n', muRes);
fprintf('    Std Residual  = %.6f\n', sigRes);
fprintf('    Tolerance     = +/- %.6f\n\n', tol);

figure('Name','Static Model Results', ...
       'NumberTitle','off', ...
       'Color','w', ...
       'Units','normalized', ...
       'Position',[0.1 0.2 0.8 0.5]);

subplot(1,2,1)
scatter(x, y, 55, 'filled');
hold on;
plot(xSort, yFitSort, 'LineWidth', 2);
plot(xSort, yUpperSort, '--', 'LineWidth', 1.5);
plot(xSort, yLowerSort, '--', 'LineWidth', 1.5);
xlabel('Applied Load');
ylabel('Measured Load');
title('Static Model Fit');
legend('Measured Data', 'Linear Fit', 'Upper Tolerance', ...
       'Lower Tolerance', 'Location', 'best');
grid on;
box on;

subplot(1,2,2)
scatter(x, res, 55, 'filled');
hold on;
yline(0, 'LineWidth', 1.5);
yline(tol, '--', 'LineWidth', 1.5);
yline(-tol, '--', 'LineWidth', 1.5);
xlabel('Applied Load');
ylabel('Residual');
title('Residual Plot');
legend('Residuals', 'Zero Line', 'Upper Tolerance', ...
       'Lower Tolerance', 'Location', 'best');
grid on;
box on;