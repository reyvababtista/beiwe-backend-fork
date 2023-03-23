import requests


production_headers = {
    'X-Access-Key-Id': "jKmCk34S8JWeCH1NRZDr56gIZFS6u5Ok2YO+vZwZEz9J/Tu703JXqsdLDoSB/8pw",
    'X-Access-Key-Secret': "L+wm0hiRmoMR0fbqFG0AQ/AHliw2rueEaomLQeRGsAburJnL3XaZR6tfaZKEgmxo",
}

nhs_headers = {
    'X-Access-Key-Id': "0MEJMEb15t7Euiy7GUJSIUu1f/lelP1hUrm0f2S3UsOcJ86dNLmlA0lAyfbFQlp4",
    'X-Access-Key-Secret': "dWZPjUJ0SB+d5mlVbHk1kMR/7Yg0uPRD73CUBXC1loBDynAvon84BlYJ/DD+cZN0",
}
staging_headers = {
    "X-Access-Key-Id": "AXaYOEqH6ry9iCD0G7w4HGkmF62FuxywCuXpOdt5/hJxy4Imc8GgKWDGHtqMep6X",
    "X-Access-Key-Secret": "YUjdcoDWpFk2xtWBvJL4l6dl7v3LrMVjsjSe5uO/pRjfwl/HEQNRU7HKNVxGFOrn",
}

STUDY_ID = "n7GersEa3WcZB83lOgGyOjZy"

response = requests.get(
    'https://' + 'nhs.beiwe.org/api/v0/studies/' + STUDY_ID + '/summary-statistics/daily',
    headers=nhs_headers,
    # params={"limit": 10000}
)




import requests

study_id="n7GersEa3WcZB83lOgGyOjZy"

server="studies"
access_key="jKmCk34S8JWeCH1NRZDr56gIZFS6u5Ok2YO+vZwZEz9J/Tu703JXqsdLDoSB/8pw"
secret_key="L+wm0hiRmoMR0fbqFG0AQ/AHliw2rueEaomLQeRGsAburJnL3XaZR6tfaZKEgmxo"

server="nhs"
access_key="0MEJMEb15t7Euiy7GUJSIUu1f/lelP1hUrm0f2S3UsOcJ86dNLmlA0lAyfbFQlp4"
secret_key="dWZPjUJ0SB+d5mlVbHk1kMR/7Yg0uPRD73CUBXC1loBDynAvon84BlYJ/DD+cZN0"

server="staging"
access_key="AXaYOEqH6ry9iCD0G7w4HGkmF62FuxywCuXpOdt5/hJxy4Imc8GgKWDGHtqMep6X"
secret_key="YUjdcoDWpFk2xtWBvJL4l6dl7v3LrMVjsjSe5uO/pRjfwl/HEQNRU7HKNVxGFOrn"



curl "https://$server.beiwe.org/api/v0/studies/$study_id/summary-statistics/daily" --max-time 900 \
  -H "X-Access-Key-Id: $access_key" \
  -H "X-Access-Key-Secret: $secret_key" > data_volume_dict.json



# response = requests.get(
#     'https://' + 'nhs.beiwe.org/api/v0/studies/' + STUDY_ID + '/summary-statistics/daily',
#     headers=nhs_headers,
#     # params={"limit": 10000}
# )


curl \
  -H "Host: 127.0.0.1:8000" \
  -H "Connection: keep-alive" \
  -H "Cache-Control: max-age=0" \
  -H "Sec-Ch-Ua: ".Not/A)Brand";v="99", "Google Chrome";v="103", "Chromium";v="103"" \
  -H "Sec-Ch-Ua-Mobile: ?0" \
  -H "Sec-Ch-Ua-Platform: "Linux"" \
  -H "Dnt: 1" \
  -H "Upgrade-Insecure-Requests: 1" \
  -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9" \
  -H "Sec-Fetch-Site: none" \
  -H "Sec-Fetch-Mode: navigate" \
  -H "Sec-Fetch-User: ?1" \
  -H "Sec-Fetch-Dest: document" \
  -H "Accept-Encoding: gzip, deflate, br" \
  -H "Accept-Language: en-US,en;q=0.9" \
  -H "Cookie: session=eyJyZXNlYXJjaGVyX3VzZXJuYW1lIjoiZGVmYXVsdF9hZG1pbiJ9.YUYspQ.IEeOD0q_bnVHjFg0DyORZBeJkVE; CSRF-Token-74IKM=rSkYxqaHPoLDFnJSjKRqnXaavFaA9d3x; sessionid=vmh3391meeouxqju7rdta4kqe4mj4kxx" "localhost/?"


curl \
  -H "Host: 127.0.0.1:8000" \
  -H "Connection: keep-alive" \
  -H "Cache-Control: max-age=0" \
  -H "Sec-Ch-Ua: \".Not/A)Brand\";v=\"99\", \"Google Chrome\";v=\"103\", \"Chromium\";v=\"103\"" \
  -H "Sec-Ch-Ua-Mobile: ?0" \
  -H "Sec-Ch-Ua-Platform: \"Linux\"" \
  -H "Dnt: 1" \
  -H "Upgrade-Insecure-Requests: 1" \
  -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9" \
  -H "Sec-Fetch-Site: none" \
  -H "Sec-Fetch-Mode: navigate" \
  -H "Sec-Fetch-User: ?1" \
  -H "Sec-Fetch-Dest: document" \
  -H "Accept-Encoding: gzip, deflate, br" \
  -H "Accept-Language: en-US,en;q=0.9" \
  -H "Cookie: session=eyJyZXNlYXJjaGVyX3VzZXJuYW1lIjoiZGVmYXVsdF9hZG1pbiJ9.YUYspQ.IEeOD0q_bnVHjFg0DyORZBeJkVE; CSRF-Token-74IKM=rSkYxqaHPoLDFnJSjKRqnXaavFaA9d3x; sessionid=vmh3391meeouxqju7rdta4kqe4mj4kxx" "localhost/?"
