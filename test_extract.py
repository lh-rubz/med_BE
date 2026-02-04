import requests
import json

# Test extraction on report 163
response = requests.post('http://localhost:5000/api/vlm/extract/163', json={}, timeout=120)
data = response.json()

print('Status:', response.status_code)
print('Total fields:', data.get('total_fields', 0))
print('Patient Name:', data.get('patient_name', ''))
print('Patient Age:', data.get('patient_age', ''))
print('Patient Gender:', data.get('patient_gender', ''))
print('Report Date:', data.get('report_date', ''))
print('Doctor:', data.get('doctor_names', ''))
print()
print('Medical Data:')
for i, field in enumerate(data.get('medical_data', [])[:10], 1):
    name = field.get('field_name', '')
    value = field.get('field_value', '')
    unit = field.get('field_unit', '')
    print(f'  {i}. {name}: {value} {unit}')
