from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

options = Options()
options.add_argument("--headless=new")
options.add_argument("--window-size=1600,2200")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")

driver = webdriver.Chrome(options=options)
try:
    driver.get("https://www.skills.sh/aahl/skills/maishou")
    time.sleep(4)
    print("title", driver.title)
    print("source_len_before", len(driver.page_source))
    print("contains_skillmd", "SKILL.md" in driver.page_source)
    print("contains_买手技能", "买手技能" in driver.page_source)
    print("contains_搜索商品_before", "搜索商品" in driver.page_source)
    buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Show more')]")
    print("show_more_buttons", len(buttons))
    if buttons:
        buttons[0].click()
        time.sleep(1.5)
        print("source_len_after", len(driver.page_source))
        print("contains_搜索商品_after", "搜索商品" in driver.page_source)
        print("contains_商品详情及购买链接", "商品详情及购买链接" in driver.page_source)
finally:
    driver.quit()
