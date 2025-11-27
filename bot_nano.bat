call ".env\Scripts\activate.bat"

python.exe -m pip install --upgrade pip

pip install -r requirements.txt
pip install markitdown[all]

python bot_nano_banan.py
