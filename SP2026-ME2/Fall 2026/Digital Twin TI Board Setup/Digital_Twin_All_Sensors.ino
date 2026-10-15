#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "HX711.h"

// ======================================================
// ADXL345 ACCELEROMETER SETUP
// ======================================================
#define ADXL345_ADDR 0x53
float scaleFactor = 256.0;

// ======================================================
// TEMPERATURE SENSOR SETUP
// ======================================================
#define TEMP1_PIN A1
#define TEMP2_PIN A2
#define TEMP3_PIN A3

OneWire oneWire1(TEMP1_PIN);
OneWire oneWire2(TEMP2_PIN);
OneWire oneWire3(TEMP3_PIN);

DallasTemperature tempSensor1(&oneWire1);
DallasTemperature tempSensor2(&oneWire2);
DallasTemperature tempSensor3(&oneWire3);

// ======================================================
// LOAD CELL SETUP
// ======================================================
// Load Cell 1
#define LOAD1_DOUT 2
#define LOAD1_CLK  1

// Load Cell 2
#define LOAD2_DOUT 4
#define LOAD2_CLK  3

HX711 scale1;
HX711 scale2;

long load1Raw = 0;
long load2Raw = 0;

// ======================================================
// VIBRATION MOTOR SETUP
// ======================================================
const int motorPin = 6;

// -------- USER PARAMETERS --------
int frequency = 10;    // Motor pulse frequency in Hz
int strength = 175;   // PWM strength: 0-255
// ---------------------------------

unsigned long previousMotorTime = 0;
bool motorState = false;

// ======================================================
// SENSOR TIMING
// ======================================================
unsigned long previousAccelTime = 0;
unsigned long previousLoadTime = 0;
unsigned long previousTempRequestTime = 0;
unsigned long tempRequestStartTime = 0;

const unsigned long accelInterval = 10;   // 100 Hz
const unsigned long loadInterval = 100;   // 10 Hz
const unsigned long tempInterval = 1000;  // request a new temperature every 1 s
const unsigned long tempConversionTime = 750; // DS18B20 12-bit conversion time

float temp1C = 0.0;
float temp2C = 0.0;
float temp3C = 0.0;
bool tempConversionInProgress = false;

// ======================================================
// SETUP
// ======================================================
void setup() {

  // 115200 is needed for reliable 100 Hz CSV output
  Serial.begin(115200);

  // ------------------------------
  // Vibration motor
  // ------------------------------
  pinMode(motorPin, OUTPUT);
  analogWrite(motorPin, 0);

  // ------------------------------
  // Temperature sensor
  // ------------------------------
  tempSensor1.begin();
  tempSensor2.begin();
  tempSensor3.begin();

  // Do not block the main loop while the DS18B20 sensors convert temperature
  tempSensor1.setWaitForConversion(false);
  tempSensor2.setWaitForConversion(false);
  tempSensor3.setWaitForConversion(false);

  // Start the first conversion on all three sensors immediately
  tempSensor1.requestTemperatures();
  tempSensor2.requestTemperatures();
  tempSensor3.requestTemperatures();
  tempRequestStartTime = millis();
  previousTempRequestTime = millis();
  tempConversionInProgress = true;

  // ------------------------------
  // Load cells
  // ------------------------------
  scale1.begin(LOAD1_DOUT, LOAD1_CLK);
  scale2.begin(LOAD2_DOUT, LOAD2_CLK);

  // ------------------------------
  // ADXL345
  // ------------------------------
  Wire.begin();

  // Measurement mode
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(0x2D);
  Wire.write(0x08);
  Wire.endTransmission();

  // Full resolution, +/- 2g
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(0x31);
  Wire.write(0x08);
  Wire.endTransmission();

  // Data rate = 100 Hz
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(0x2C);
  Wire.write(0x0A);
  Wire.endTransmission();

  // CSV header
  Serial.println("Time_ms,X_g,Y_g,Z_g,Temp_A1_C,Temp_A2_C,Temp_A3_C,LoadCell1_Raw,LoadCell2_Raw,Motor");
}

// ======================================================
// MAIN LOOP
// ======================================================
void loop() {

  runMotor();
  readTemperature();
  readLoadCells();
  readAccelerometerAndPrint();
}

// ======================================================
// MOTOR FUNCTION
// ======================================================
void runMotor() {

  // Avoid division by zero if frequency is accidentally set to 0
  if (frequency <= 0) {
    motorState = false;
    analogWrite(motorPin, 0);
    return;
  }

  unsigned long period = 1000UL / frequency;
  unsigned long halfPeriod = period / 2;

  if (halfPeriod < 1) {
    halfPeriod = 1;
  }

  if (millis() - previousMotorTime >= halfPeriod) {

    previousMotorTime = millis();
    motorState = !motorState;

    if (motorState == true) {
      analogWrite(motorPin, strength);
    }
    else {
      analogWrite(motorPin, 0);
    }
  }
}

// ======================================================
// NON-BLOCKING TEMPERATURE FUNCTION
// ======================================================
void readTemperature() {

  unsigned long currentTime = millis();

  // If a conversion is running and enough time has passed, read it
  if (tempConversionInProgress == true) {

    if (currentTime - tempRequestStartTime >= tempConversionTime) {
      temp1C = tempSensor1.getTempCByIndex(0);
      temp2C = tempSensor2.getTempCByIndex(0);
      temp3C = tempSensor3.getTempCByIndex(0);
      tempConversionInProgress = false;
    }
  }

  // Start another conversion once per second
  if (tempConversionInProgress == false &&
      currentTime - previousTempRequestTime >= tempInterval) {

    tempSensor1.requestTemperatures();
    tempSensor2.requestTemperatures();
    tempSensor3.requestTemperatures();
    tempRequestStartTime = currentTime;
    previousTempRequestTime = currentTime;
    tempConversionInProgress = true;
  }
}

// ======================================================
// LOAD CELL FUNCTION
// ======================================================
void readLoadCells() {

  if (millis() - previousLoadTime >= loadInterval) {

    previousLoadTime = millis();

    // Read Load Cell 1 only when new HX711 data is available
    if (scale1.is_ready()) {
      load1Raw = scale1.read();
    }

    // Read Load Cell 2 only when new HX711 data is available
    if (scale2.is_ready()) {
      load2Raw = scale2.read();
    }
  }
}

// ======================================================
// ACCELEROMETER + CSV OUTPUT FUNCTION
// ======================================================
void readAccelerometerAndPrint() {

  if (millis() - previousAccelTime >= accelInterval) {

    previousAccelTime = millis();

    int16_t xRaw;
    int16_t yRaw;
    int16_t zRaw;

    // Start reading at X-axis data register
    Wire.beginTransmission(ADXL345_ADDR);
    Wire.write(0x32);
    Wire.endTransmission(false);

    // Request X, Y, Z = 6 bytes
    Wire.requestFrom(ADXL345_ADDR, 6, true);

    if (Wire.available() >= 6) {

      xRaw = Wire.read() | (Wire.read() << 8);
      yRaw = Wire.read() | (Wire.read() << 8);
      zRaw = Wire.read() | (Wire.read() << 8);

      float xg = xRaw / scaleFactor;
      float yg = yRaw / scaleFactor;
      float zg = zRaw / scaleFactor;

      // One synchronized CSV row every ~10 ms.
      // Temperature and load-cell columns contain the latest available values.
      Serial.print(millis());
      Serial.print(",");

      Serial.print(xg, 4);
      Serial.print(",");

      Serial.print(yg, 4);
      Serial.print(",");

      Serial.print(zg, 4);
      Serial.print(",");

      Serial.print(temp1C, 2);
      Serial.print(",");

      Serial.print(temp2C, 2);
      Serial.print(",");

      Serial.print(temp3C, 2);
      Serial.print(",");

      Serial.print(load1Raw);
      Serial.print(",");

      Serial.print(load2Raw);
      Serial.print(",");

      if (motorState == true) {
        Serial.println("ON");
      }
      else {
        Serial.println("OFF");
      }
    }
  }
}
