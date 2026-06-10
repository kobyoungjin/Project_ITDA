import sys
import os

sys.path.append(r"c:\Users\ComHolic\Documents\GitHub\Project_ITDA_backup")
from api.services.motion_tokenizer import motion_tokenizer

print("Testing '사랑합니다':", [t for t in motion_tokenizer.tokenize("사랑합니다") if t['source'] != 'unknown'])
print("Testing '사랑 합니다':", [t for t in motion_tokenizer.tokenize("사랑 합니다") if t['source'] != 'unknown'])
print("Testing '다 주스':", [t for t in motion_tokenizer.tokenize("다 주스") if t['source'] != 'unknown'])
