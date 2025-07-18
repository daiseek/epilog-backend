''' ElevenLabs TTS 음성 ID 매핑 테이블 '''
# 사이트에서 명시된 voice id와 성별, 나이에 맞게 매핑시킴
# 서버가 이 테이블을 사용해 voice id 선택
VOICE_SELECTION_TABLE = {
    # 여성
    ("여성", "teen"): "sSoVF9lUgTGJz0Xz3J9y",      # 
    ("여성", "adult"): "ksaI0TCD9BstzEzlxj4q",     # 
    ("여성", "senior"): "8MwPLtBplylvbrksiBOC",    # 
    ("여성", "else"): "CnnL9KfZBW3JEUs1JPeS",  # 동물

    # 남성
    ("남성", "teen"): "4JJwo477JUAx3HV0T7n7",      # 
    ("남성", "adult"): "ZJCNdZEjYwkOElxugmW2",   # 
    ("남성", "senior"): "5ON5Fnz24cnOozEQfGAm",    # 
    ("남성", "else"): "4JJwo477JUAx3HV0T7n7",  # 

}
