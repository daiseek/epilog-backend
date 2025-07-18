''' ElevenLabs TTS 음성 ID 매핑 테이블 '''
# 사이트에서 명시된 voice id와 성별, 나이에 맞게 매핑시킴
# 서버가 이 테이블을 사용해 voice id 선택
VOICE_SELECTION_TABLE = {
    # 여성
    ("여성", "teen"): "ZJCNdZEjYwkOElxugmW2",      # Bella
    ("여성", "adult"): "ZJCNdZEjYwkOElxugmW2",     # Rachel
    ("여성", "senior"): "ZJCNdZEjYwkOElxugmW2",    # Rachel (대체용)

    # 남성
    ("남성", "teen"): "ZJCNdZEjYwkOElxugmW2",      # Domi (중성 느낌)
    ("남성", "adult"): "ZJCNdZEjYwkOElxugmW2",     # Clyde
    ("남성", "senior"): "ZJCNdZEjYwkOElxugmW2",    # Arnold
}
