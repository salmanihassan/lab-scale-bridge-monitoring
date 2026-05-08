import paho.mqtt.client as mqtt
import ssl
import json
import csv
import time
import os
from datetime import datetime

# --- Configuration ---
BROKER_IP = "127.0.0.1"
BROKER_PORT = 8883
TOPIC = "cc32xx/telemetry"
CSV_FILENAME = "raw_dataset_encrypted.csv"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

# --- Performance Tracking Variables ---
expected_seq_num = None
packets_received = 0
packets_lost = 0
start_time = None

# Initialize CSV File with Headers
with open(CSV_FILENAME, mode='a', newline='') as file:
    writer = csv.writer(file)
    # Write header only if the file is empty
    if file.tell() == 0:
        writer.writerow(["Host_Timestamp", "Device_ID", "Seq_Num", "Board_Time_ms", "Temp_C", "Humidity_%"])

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to Mosquitto Broker at {BROKER_IP}:{BROKER_PORT} (TLS)")
        client.subscribe(TOPIC)
        print(f"Subscribed to topic: {TOPIC}")
        print(f"CA certificate: {CA_CERT}")
        print("Waiting for DHT11 sensor data...\n")
    else:
        print(f"Failed to connect. Return code: {rc}")

def on_message(client, userdata, msg):
    global expected_seq_num, packets_received, packets_lost, start_time
    
    # Start timer on first packet for throughput calculation
    if packets_received == 0:
        start_time = time.time()
        
    try:
        # Decode the payload
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        
        host_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        device_id = data.get("device_id", "UNKNOWN")
        seq_num = data.get("seq_num", 0)
        board_time = data.get("timestamp_ms", 0)
        
        # Extract DHT11 Telemetry
        telemetry = data.get("telemetry", {})
        temp = telemetry.get("temperature_c", "N/A")
        humidity = telemetry.get("humidity", "N/A")

        # --- Packet Loss Validation ---
        if expected_seq_num is not None:
            if seq_num > expected_seq_num:
                loss = seq_num - expected_seq_num
                packets_lost += loss
                print(f"[WARNING] Packet jump detected! Lost {loss} packets.")
        
        expected_seq_num = seq_num + 1
        packets_received += 1

        # --- Logging ---
        with open(CSV_FILENAME, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([host_timestamp, device_id, seq_num, board_time, temp, humidity])

        print(f"[{host_timestamp}] Logged Seq: {seq_num} | Temp: {temp}°C | Hum: {humidity}%")

    except json.JSONDecodeError:
        print(f"Failed to parse JSON: {msg.payload}")
    except Exception as e:
        print(f"Error processing message: {e}")

# --- Setup MQTT Client ---
client = mqtt.Client(client_id="MacHostReceiver")
client.on_connect = on_connect
client.on_message = on_message

client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)

print("Starting Encrypted Data Ingestion Engine...")
print(f"Connecting to {BROKER_IP}:{BROKER_PORT} with TLS...")
client.connect(BROKER_IP, BROKER_PORT, 60)

try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\n--- Ingestion Stopped ---")
    
    # Calculate Basic Performance Notes
    if start_time and packets_received > 0:
        elapsed_time = time.time() - start_time
        throughput = packets_received / elapsed_time
        loss_rate = (packets_lost / (packets_received + packets_lost)) * 100 if (packets_received + packets_lost) > 0 else 0
        
        print("\n--- Week 4 Performance Notes ---")
        print(f"Total Time:         {elapsed_time:.2f} seconds")
        print(f"Packets Received:   {packets_received}")
        print(f"Packets Lost:       {packets_lost}")
        print(f"Throughput:         {throughput:.2f} packets/sec")
        print(f"Packet Loss Rate:   {loss_rate:.2f}%")
        print(f"Dataset saved to:   {CSV_FILENAME}")
