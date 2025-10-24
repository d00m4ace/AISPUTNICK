call ".env\Scripts\activate.bat"

pip install -r requirements.txt
pip install markitdown[all]

python doc_sync\doc_sync.py --config NETHACK/acmecorp/config.json
