import requests

url = 'http://127.0.0.1:5000/upload'
files = {
    'questions[]': open('test_question_paper_input.txt', 'rb'),
}
print("Sending request...")
response = requests.post(url, files=files)
print(response.json())
