call ".env\Scripts\activate.bat"

pip install -r requirements.txt
pip install markitdown[all]

python doc_sync\doc_sum.py --config NETHACK/acmecorp/config_sum.json
