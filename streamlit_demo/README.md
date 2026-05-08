# DecisionMiner Page 1 시연 페이지

## 실행 방법
1. `pip install -r requirements.txt`
2. `streamlit run streamlit_page1.py`
3. 브라우저에서 http://localhost:8501 자동 열림
4. "시연 시작" 버튼 클릭

## 시연 시간
약 15초 (Step 1~5 자동 진행)

## 표본 사건
쿠팡(주)의 전자상거래소비자보호법 등 위반행위에 대한 건

## 데이터 출처
- 5단 분해 결과: 04_raw_outputs/
- QA 원본: 11_data_quality/qa_evaluated_990.csv
- 검수 결과: 11_data_quality/qc_result_990.csv
- 메타 데이터: 11_data_quality/dataset_*.csv

## 시연 데이터 갱신
원본 데이터가 바뀐 경우 다음 명령으로 시연용 JSON을 재생성:
```
python build_demo_data.py
```
