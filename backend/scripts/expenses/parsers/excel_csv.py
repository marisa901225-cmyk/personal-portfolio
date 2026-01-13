"""Excel/CSV 파일 파서"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


# 컬럼 매핑 (다양한 형식 지원)
COLUMN_MAPPING = {
    # 날짜
    'date': [
        'date', '일자', '거래일', '거래일자', '날짜', '승인일자', '이용일', '거래일시',
    ],
    # 시간
    'time': ['time', '이용시간', '거래시각'],
    # 가맹점
    'merchant': [
        'merchant', '가맹점', '가맹점명', '상호', '적요', '내역', '거래처', '사용처',
        '이용가맹점(은행)명', '이용하신곳',
    ],
    # 금액
    'amount': [
        'amount', '금액', '거래금액', '이용금액', '승인금액', '출금', '입금',
        '이용금액(원)', '국내이용금액(원)', '해외이용금액($)', '출금액', '입금액',
    ],
    # 입금/출금 분리형
    'withdrawal': ['withdrawal', '출금', '출금액'],
    'deposit': ['deposit', '입금', '입금액'],
    # 결제수단
    'method': ['method', '결제수단', '카드', '카드명', '계좌', '은행', '수단', '이용카드', '이용카드명'],
}


def normalize_col(col: str) -> str:
    """컬럼명 정규화 (대소문자, 공백 제거)"""
    return re.sub(r"\s+", "", str(col).strip().lower())


def map_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """컬럼명을 표준 이름으로 매핑"""
    mapped_df = pd.DataFrame()
    mapped_from = {}
    col_map = {normalize_col(c): c for c in df.columns}
    
    for standard_col, possible_names in COLUMN_MAPPING.items():
        for col_name in possible_names:
            normalized_name = normalize_col(col_name)
            if normalized_name in col_map:
                original_col = col_map[normalized_name]
                mapped_df[standard_col] = df[original_col]
                mapped_from[standard_col] = normalized_name
                break
    
    return mapped_df, mapped_from


def find_header_row(df_raw: pd.DataFrame, max_scan: int = 30) -> int | None:
    """엑셀에서 실제 헤더 행 찾기"""
    header_candidates = {normalize_col(n) for names in COLUMN_MAPPING.values() for n in names}
    max_scan = min(max_scan, len(df_raw))
    
    for idx in range(max_scan):
        row_values = df_raw.iloc[idx].astype(str).apply(normalize_col)
        hits = sum(1 for v in row_values if v in header_candidates)
        if hits >= 2:
            return idx
    return None


def process_deposit_withdrawal(mapped_df: pd.DataFrame, mapped_from: dict) -> None:
    """입금/출금 분리형 처리"""
    if 'withdrawal' in mapped_df.columns and 'deposit' in mapped_df.columns:
        mapped_df['withdrawal'] = pd.to_numeric(
            mapped_df['withdrawal'].astype(str).str.replace(',', '').str.replace(' ', ''),
            errors='coerce',
        ).fillna(0)
        mapped_df['deposit'] = pd.to_numeric(
            mapped_df['deposit'].astype(str).str.replace(',', '').str.replace(' ', ''),
            errors='coerce',
        ).fillna(0)
        mapped_df['amount'] = mapped_df['deposit'] - mapped_df['withdrawal']
        mapped_from['amount'] = 'deposit-withdrawal'


def parse_report_xls(file_path: Path) -> pd.DataFrame:
    """report.xls 계열 카드내역 전용 파서 (우리카드 등)"""
    df_raw = pd.read_excel(file_path, header=None)
    df_report = pd.read_excel(file_path, header=1)
    df_report.columns = [normalize_col(c) for c in df_report.columns]
    
    mapped_df, _ = map_columns(df_report)
    
    required = ['date', 'merchant', 'amount']
    missing = [col for col in required if col not in mapped_df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}\n현재 컬럼: {list(df_report.columns)}")
    
    if 'method' not in mapped_df.columns:
        mapped_df['method'] = file_path.stem
    
    # 날짜 추출: 헤더에서 연도 찾기
    raw_dates = mapped_df['date'].astype(str)
    header_text = " ".join(df_raw.astype(str).head(5).fillna("").values.flatten())
    year_match = re.search(r"(20\d{2})\.\d{2}\.\d{2}", header_text)
    if year_match:
        year = year_match.group(1)
        date_str = year + "." + raw_dates
        mapped_df['date'] = pd.to_datetime(date_str, format="%Y.%m.%d %H:%M:%S", errors='coerce')
    
    # 금액 처리
    mapped_df['amount'] = mapped_df['amount'].astype(str).str.replace(',', '').str.replace(' ', '')
    mapped_df['amount'] = pd.to_numeric(mapped_df['amount'], errors='coerce')
    mapped_df['amount'] = -mapped_df['amount'].abs()  # 카드는 지출이므로 음수
    
    # 가맹점 정리
    mapped_df['merchant'] = mapped_df['merchant'].astype('string').str.strip()
    mapped_df.loc[mapped_df['merchant'] == '', 'merchant'] = pd.NA
    
    # 유효하지 않은 행 제거
    before_drop = len(mapped_df)
    mapped_df = mapped_df.dropna(subset=['date', 'merchant', 'amount'])
    dropped = before_drop - len(mapped_df)
    if dropped:
        print(f"⚠️ 유효하지 않은 {dropped}행을 제외했습니다.")
    
    if mapped_df.empty:
        raise ValueError("유효한 거래를 찾지 못했습니다.")
    
    return mapped_df


def parse_excel_or_csv(file_path: Path) -> pd.DataFrame:
    """
    Excel 또는 CSV 파일을 읽어서 표준 형식으로 변환
    
    필수 컬럼:
    - date (거래일): YYYY-MM-DD 또는 YYYYMMDD
    - merchant (가맹점): 상점명
    - amount (금액): 숫자 (음수: 지출, 양수: 수입)
    - method (결제수단): 카드명 또는 계좌명
    
    Returns:
        표준화된 DataFrame
    """
    # report.xls 계열은 별도 처리
    if file_path.suffix == '.xls' and file_path.stem.startswith('report'):
        return parse_report_xls(file_path)
    
    # 파일 읽기
    if file_path.suffix in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    elif file_path.suffix == '.csv':
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding='cp949')
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {file_path.suffix}")
    
    # 컬럼명 정규화
    df.columns = [normalize_col(c) for c in df.columns]
    
    # 컬럼 자동 매핑
    mapped_df, mapped_from = map_columns(df)
    header_text_source = df
    
    # 헤더가 위에 있는 특수 엑셀 형식 대응
    if 'date' not in mapped_df.columns or 'merchant' not in mapped_df.columns or 'amount' not in mapped_df.columns:
        df_raw = pd.read_excel(file_path, header=None) if file_path.suffix in ['.xlsx', '.xls'] else df
        header_text_source = df_raw
        header_row = find_header_row(df_raw)
        
        if header_row is not None:
            df = df_raw.iloc[header_row:].copy()
            df.columns = [normalize_col(c) for c in df.iloc[0]]
            df = df.iloc[1:].reset_index(drop=True)
            mapped_df, mapped_from = map_columns(df)
    
    # 입금/출금 분리형 처리
    process_deposit_withdrawal(mapped_df, mapped_from)
    
    # 날짜 + 시간 컬럼 결합
    if 'date' in mapped_df.columns and 'time' in mapped_df.columns:
        mapped_df['date'] = mapped_df['date'].astype(str).str.strip() + " " + mapped_df['time'].astype(str).str.strip()
    
    # 필수 컬럼 확인
    required = ['date', 'merchant', 'amount']
    missing = [col for col in required if col not in mapped_df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}\n현재 컬럼: {list(df.columns)}")
    
    return mapped_df

    # method가 없으면 파일명에서 추출
    if 'method' not in mapped_df.columns:
        mapped_df['method'] = file_path.stem
    
    # 날짜 형식 변환
    raw_dates = mapped_df['date'].astype(str)
    mapped_df['date'] = pd.to_datetime(mapped_df['date'], errors='coerce')
    
    # [FIX] 파일명에서 연도 추출 (가장 우선순위 높음)
    filename_year = None
    year_match = re.search(r"(20\d{2})", file_path.stem)
    if year_match:
        filename_year = year_match.group(1)
        
    # 날짜 파싱 실패 시 또는 파일명에 연도가 있는 경우 보정
    if mapped_df['date'].isna().any() or filename_year:
        # 헤더에서 연도 찾기 (파일명 연도가 없으면 fallback)
        header_year = None
        if not filename_year:
            header_text = " ".join(header_text_source.astype(str).head(10).fillna("").values.flatten())
            header_match = re.search(r"(20\d{2})\.\d{2}\.\d{2}", header_text)
            if header_match:
                header_year = header_match.group(1)
        
        target_year = filename_year or header_year
        
        if target_year:
            # 기존 파싱된 날짜가 있어도 연도가 다르면 교체, 아니면 새로 파싱
            def fix_year(d, y):
                if pd.isna(d):
                    return d
                try:
                    # 원본 문자열에서 월/일 추출 시도 (단순 파싱)
                    # 이미 파싱된 d가 있다면 월/일은 믿을 수 있음 -> 연도만 교체
                    return d.replace(year=int(y))
                except:
                    return d

            # 날짜가 NaT인 경우 원본 문자열과 target_year 조합 시도
            if mapped_df['date'].isna().any():
                # 포맷 추정 (점. 구분)
                date_str = target_year + "." + raw_dates
                # 이미 점이 포함된 짧은 형식(12.31 등)이라고 가정
                # 하지만 raw_dates가 이미 '2025-12-31' 포맷일 수도 있음.
                # 단순하게: 우선 pd.to_datetime으로 파싱된 것의 연도를 강제 변경
                pass

            # 1. 일단 다시 파싱 (연도 붙여서) - raw_dates가 'MM.DD' 형식일 때 유효
            #    raw_dates가 이미 'YYYY...' 형식이면 꼬일 수 있음.
            #    따라서 'MM.DD' 패턴인지 확인 필요
            
            # 전략: 
            # 1) 파싱 성공한 날짜들 -> filename_year로 연도 교체
            # 2) 파싱 실패한 날짜들 -> 'Year.Raw' 로 다시 시도
            
            if filename_year:
                # 파싱 성공한 것들 연도 교체
                mask_ok = mapped_df['date'].notna()
                if mask_ok.any():
                    mapped_df.loc[mask_ok, 'date'] = mapped_df.loc[mask_ok, 'date'].apply(lambda x: x.replace(year=int(filename_year)))
            
            # 파싱 실패한 것들 (또는 아직 처리 안된 것들)
            mask_na = mapped_df['date'].isna()
            if mask_na.any():
                # 'MM.DD' 형태라고 가정하고 연도 붙이기
                # raw_dates에 이미 연도가 있을 수도 있으니 주의.
                # 하지만 보통 엑셀에서 날짜가 깨지면 텍스트로 오거나...
                # 여기서는 'MM.DD' 텍스트로 온 경우를 상정
                
                # 원본 텍스트 정제 (점 구분 가정)
                clean_dates = raw_dates[mask_na].str.strip()
                # 20xx로 시작하지 않는 경우만 처리
                needs_year = ~clean_dates.str.match(r'^20\d{2}')
                
                if needs_year.any():
                    date_str = target_year + "." + clean_dates[needs_year]
                    mapped_df.loc[mask_na & needs_year, 'date'] = pd.to_datetime(date_str, errors='coerce')

    
    # 금액 형식 변환 (쉼표 제거)
    mapped_df['amount'] = mapped_df['amount'].astype(str).str.replace(',', '').str.replace(' ', '')
    mapped_df['amount'] = pd.to_numeric(mapped_df['amount'], errors='coerce').astype(float)
    
    # 해외 사용 내역: 국내 금액이 0이면 해외 금액으로 보정
    col_map = {normalize_col(c): c for c in df.columns}
    overseas_col_name = normalize_col('해외이용금액($)')
    if overseas_col_name in col_map:
        overseas_col = col_map[overseas_col_name]
        overseas_amount = df[overseas_col].astype(str).str.replace(',', '').str.replace(' ', '')
        overseas_amount = pd.to_numeric(overseas_amount, errors='coerce')
        mask = (mapped_df['amount'].isna() | (mapped_df['amount'] == 0)) & overseas_amount.notna() & (overseas_amount != 0)
        if mask.any():
            mapped_df.loc[mask, 'amount'] = overseas_amount[mask]
    
    # 카드 이용내역은 지출로 음수 처리
    normalized_cols = set(df.columns)
    if (
        any(x in normalized_cols for x in ['이용금액(원)', '국내이용금액(원)', '이용하신곳', '이용가맹점(은행)명'])
        or '카드' in file_path.stem
    ) and 'deposit' not in mapped_df.columns:
        mapped_df['amount'] = -mapped_df['amount'].abs()
    
    # 가맹점 정리
    mapped_df['merchant'] = mapped_df['merchant'].astype('string').str.strip()
    mapped_df.loc[mapped_df['merchant'] == '', 'merchant'] = pd.NA
    
    # 유효하지 않은 행 제거
    invalid_date_count = mapped_df['date'].isna().sum()
    invalid_amount_count = mapped_df['amount'].isna().sum()
    invalid_merchant_count = mapped_df['merchant'].isna().sum()
    before_drop = len(mapped_df)
    mapped_df = mapped_df.dropna(subset=['date', 'merchant', 'amount'])
    dropped = before_drop - len(mapped_df)
    if dropped:
        print(
            f"⚠️ 유효하지 않은 {dropped}행을 제외했습니다. "
            f"(날짜 {invalid_date_count} / 금액 {invalid_amount_count} / 가맹점 {invalid_merchant_count})"
        )
    
    if mapped_df.empty:
        raise ValueError("유효한 거래를 찾지 못했습니다. 날짜/금액/가맹점 컬럼을 확인해주세요.")
    
    return mapped_df
