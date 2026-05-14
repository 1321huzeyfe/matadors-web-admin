from supabase_client import supabase

try:
    result = supabase.table("customers").select("*").limit(1).execute()
    print("SUPABASE BAGLANTI BASARILI")
    print(result)
except Exception as e:
    print("HATA:")
    print(e)