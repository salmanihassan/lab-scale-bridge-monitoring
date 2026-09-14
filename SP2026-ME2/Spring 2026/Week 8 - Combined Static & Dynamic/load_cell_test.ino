#include "HX711.h"
#include <Wire.h>
#include <math.h>

// ===============================
// HX711 objects
// ===============================
HX711 scale1;
HX711 scale2;

// Pin definitions (kept exactly as requested)
#define DOUT1  2
#define SCK1   1

#define DOUT2  4
#define SCK2   3

// ===============================
// Vibration motor
// ===============================
#define MOTOR_PWM 5

// ===============================
// ADXL345 I2C settings
// ===============================
#define ADXL345_ADDR 0x53

float ax_g = 0.0;
float ay_g = 0.0;
float az_g = 0.0;
float accelMag_g = 0.0;

// Motor PWM variables
int motorPWM = 0;
int pwmStep = 15;

// ===============================
// Function: write one byte to ADXL345
// ===============================
void writeRegister(byte reg, byte value) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

// ===============================
// Function: initialize ADXL345
// ===============================
void initADXL345() {
  // Put device into standby first
  writeRegister(0x2D, 0x00);
  delay(10);

  // Full resolution, +/-2g range
  writeRegister(0x31, 0x08);
  delay(10);

  // Output data rate = 100 Hz
  writeRegister(0x2C, 0x0D);
  delay(10);

  // Put device into measurement mode
  writeRegister(0x2D, 0x08);
  delay(10);
}

// ===============================
// Function: read ADXL345 raw data
// ===============================
void readADXL345() {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(0x32);   // DATAX0
  Wire.endTransmission(false);

  Wire.requestFrom(ADXL345_ADDR, 6, true);

  if (Wire.available() == 6) {
    int16_t rawX = Wire.read() | (Wire.read() << 8);
    int16_t rawY = Wire.read() | (Wire.read() << 8);
    int16_t rawZ = Wire.read() | (Wire.read() << 8);

    // ADXL345 full-resolution scale factor ≈ 3.9 mg/LSB
    ax_g = rawX * 0.0039;
    ay_g = rawY * 0.0039;
    az_g = rawZ * 0.0039;

    accelMag_g = sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
  }
}

// ===============================
// Setup
// ===============================
void setup() {
  Serial.begin(9600);
  delay(1000);

  // Initialize HX711s
  scale1.begin(DOUT1, SCK1);
  scale2.begin(DOUT2, SCK2);

  scale1.set_scale();
  scale1.tare();

  scale2.set_scale();
  scale2.tare();

  // Initialize I2C and ADXL345
  Wire.begin();
  initADXL345();

  // Initialize motor pin
  pinMode(MOTOR_PWM, OUTPUT);
  analogWrite(MOTOR_PWM, 0);

  // Header for Serial Plotter / CSV
  Serial.println("LC1,LC2,VibeMag,X,Y,Z");
}

// ===============================
// Loop
// ===============================
void loop() {
  // Read load cells
  float reading1 = scale1.get_units(1);
  float reading2 = scale2.get_units(1);

  // Read accelerometer
  readADXL345();

  // Simple motor PWM ramp up/down
  analogWrite(MOTOR_PWM, motorPWM);
  motorPWM += pwmStep;

  if (motorPWM >= 255) {
    motorPWM = 255;
    pwmStep = -pwmStep;
  }
  else if (motorPWM <= 0) {
    motorPWM = 0;
    pwmStep = -pwmStep;
  }

  // Serial Plotter output: 6 traces
  Serial.print(reading1);
  Serial.print(",");
  Serial.print(reading2);
  Serial.print(",");
  Serial.print(accelMag_g);
  Serial.print(",");
  Serial.print(ax_g);
  Serial.print(",");
  Serial.print(ay_g);
  Serial.print(",");
  Serial.println(az_g);

  delay(10);   // 10 Hz
}