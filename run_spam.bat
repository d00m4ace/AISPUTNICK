call ".env\Scripts\activate.bat"

pip install -r requirements.txt
pip install markitdown[all]

python code\spam_manager_bot.py 
