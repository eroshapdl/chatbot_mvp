from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

try:
    # Use system ChromeDriver (no webdriver-manager)
    driver = webdriver.Chrome(options=options)
    print('Chrome automation works!')
    driver.get('https://www.messenger.com')
    print('Messenger opened successfully')
    input('Press Enter to close...')
    driver.quit()
except Exception as e:
    print(f'Error: {e}')