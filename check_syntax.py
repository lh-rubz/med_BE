try:
    import utils.vlm_prompts
    print("Syntax OK")
except SyntaxError as e:
    print(f"Syntax Error: {e}")
except Exception as e:
    print(f"Other Error: {e}")
