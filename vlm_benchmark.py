import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForCausalLM, LlavaForConditionalGeneration
import evaluate
from nltk.tokenize import word_tokenize
import nltk

# Download NLTK data (required for METEOR/BLEU tokenization)
nltk.download('punkt')
nltk.download('wordnet')

class VLMEvaluator:
    def __init__(self):
        # Initialize metrics
        self.bleu = evaluate.load("bleu")
        self.rouge = evaluate.load("rouge")
        self.meteor = evaluate.load("meteor")
        # Note: CIDEr usually requires a specific implementation or COCO-eval tools.
        # Here we assume a Hugging Face compatible 'cider' metric wrapper or custom implementation.
        # If 'cider' is not available in 'evaluate', one often uses pycocoevalcap.
        # For this script, we will use a placeholder or available generic metrics.
        
    def load_model(self, model_name):
        """
        Factory method to load specific VLM models.
        Note: 'Gemma 3' and 'LLaMA 4' are placeholders for future models.
        We map them to compatible classes or existing checkpoints for demonstration.
        """
        print(f"Loading {model_name}...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        if model_name == "LLaVA":
            # Example: loading LLaVA-1.5-7b-hf
            processor = AutoProcessor.from_pretrained("llava-hf/llava-1.5-7b-hf")
            model = LlavaForConditionalGeneration.from_pretrained(
                "llava-hf/llava-1.5-7b-hf", 
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                low_cpu_mem_usage=True
            ).to(device)
            
        elif model_name == "Gemma 3":
            # PLACEHOLDER: Assuming Gemma 3 follows similar VLM API or Paligemma
            # Using Paligemma checkpoint as a proxy for "Gemma-based VLM"
            processor = AutoProcessor.from_pretrained("google/paligemma-3b-pt-224")
            model = AutoModelForCausalLM.from_pretrained(
                "google/paligemma-3b-pt-224",
                torch_dtype=torch.float16 if device == "cuda" else torch.float32
            ).to(device)
            
        elif model_name == "LLaMA 4":
            # PLACEHOLDER: Using Llama-3.2-11B-Vision as proxy for LLaMA 4
            processor = AutoProcessor.from_pretrained("meta-llama/Llama-3.2-11B-Vision")
            model = AutoModelForCausalLM.from_pretrained(
                "meta-llama/Llama-3.2-11B-Vision",
                torch_dtype=torch.float16 if device == "cuda" else torch.float32
            ).to(device)
            
        else:
            raise ValueError(f"Unknown model: {model_name}")
            
        return model, processor, device

    def generate_caption(self, model, processor, image, device, model_name="LLaVA"):
        """Generates a caption for a single PIL image."""
        
        # Prompt formatting depends on the model
        if model_name == "LLaVA":
            prompt = "USER: <image>\nDescribe this image.\nASSISTANT:"
        elif model_name == "Gemma 3":
            prompt = "caption en" # Paligemma style prompt
        else: # LLaMA 4 / Generic
            prompt = "<|image|>Describe this image."

        inputs = processor(text=prompt, images=image, return_tensors="pt").to(device)
        
        # Generate
        with torch.no_grad():
            generated_ids = model.generate(
                **inputs, 
                max_new_tokens=50,
                do_sample=False
            )
            
        # Decode
        generated_text = processor.batch_decode(
            generated_ids, 
            skip_special_tokens=True, 
            clean_up_tokenization_spaces=True
        )[0]
        
        # Post-processing to remove prompt artifacts
        if model_name == "LLaVA":
            generated_text = generated_text.split("ASSISTANT:")[-1].strip()
        
        return generated_text

    def evaluate_batch(self, model_name, dataset):
        """
        dataset: list of dicts {'image': PIL.Image, 'references': ['caption1', 'caption2']}
        """
        model, processor, device = self.load_model(model_name)
        
        predictions = []
        references = []
        
        print(f"Generating captions for {model_name}...")
        for item in dataset:
            caption = self.generate_caption(model, processor, item['image'], device, model_name)
            predictions.append(caption)
            references.append(item['references'])
            
        # Calculate scores
        print("Calculating metrics...")
        
        # BLEU
        bleu_score = self.bleu.compute(predictions=predictions, references=references)
        
        # ROUGE
        rouge_score = self.rouge.compute(predictions=predictions, references=references)
        
        # METEOR
        meteor_score = self.meteor.compute(predictions=predictions, references=references)
        
        # CIDEr (Mock implementation for demo as it requires pycocoevalcap)
        # In a real notebook, install pycocoevalcap and use it here
        cider_score = {"cider": 0.0} 
        
        results = {
            "Model": model_name,
            "BLEU-4": round(bleu_score.get('bleu', 0) * 100, 2),
            "ROUGE-L": round(rouge_score.get('rougeL', 0) * 100, 2),
            "METEOR": round(meteor_score.get('meteor', 0) * 100, 2),
            "CIDEr": "N/A" # Requires extra setup
        }
        
        # Cleanup to save memory
        del model
        del processor
        torch.cuda.empty_cache()
        
        return results

# Example Usage
if __name__ == "__main__":
    # Dummy Dataset Creation (Replace with real loading logic, e.g., from COCO)
    # dataset = [
    #     {'image': Image.open("test1.jpg"), 'references': ["A cat sitting on a mat."]},
    #     {'image': Image.open("test2.jpg"), 'references': ["A dog running in the park."]}
    # ]
    
    # print("Starting Evaluation...")
    # evaluator = VLMEvaluator()
    
    # models_to_test = ["LLaVA", "Gemma 3", "LLaMA 4"]
    # final_results = []
    
    # for m_name in models_to_test:
    #     try:
    #         res = evaluator.evaluate_batch(m_name, dataset)
    #         final_results.append(res)
    #         print(f"Results for {m_name}: {res}")
    #     except Exception as e:
    #         print(f"Failed to evaluate {m_name}: {e}")
    
    pass
