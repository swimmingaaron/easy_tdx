"""Unit tests for stock universe automatic new stock detection and expansion."""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from easy_tdx.screener.universe import (
    is_valid_ashare_code,
    register_new_stocks,
    sync_new_stocks,
    get_universe_symbols,
    _load_all_ashares,
    CORE_UNIVERSE,
)


def test_is_valid_ashare_code():
    # Valid Shanghai
    assert is_valid_ashare_code("600519") is True
    assert is_valid_ashare_code("601318") is True
    assert is_valid_ashare_code("603288") is True
    assert is_valid_ashare_code("605111") is True
    assert is_valid_ashare_code("688981") is True

    # Valid Shenzhen
    assert is_valid_ashare_code("000001") is True
    assert is_valid_ashare_code("001381") is True
    assert is_valid_ashare_code("002475") is True
    assert is_valid_ashare_code("300750") is True
    assert is_valid_ashare_code("301718") is True

    # Valid BSE
    assert is_valid_ashare_code("920001") is True
    assert is_valid_ashare_code("831234") is True

    # Invalid codes
    assert is_valid_ashare_code("12345") is False     # 5 digits
    assert is_valid_ashare_code("510300") is False    # ETF
    assert is_valid_ashare_code("159915") is False    # ETF
    assert is_valid_ashare_code("113008") is False    # Convertible bond
    assert is_valid_ashare_code("00247A") is False    # Non-digit
    assert is_valid_ashare_code("") is False


def test_register_new_stocks(tmp_path):
    initial_all = get_universe_symbols("all")
    initial_cnt = len(initial_all)

    # Test registering non-existent valid codes
    mock_new_code1 = "688998"
    mock_new_code2 = "301999"
    # Ensure they don't happen to be in the baseline
    if mock_new_code1 in initial_all:
        mock_new_code1 = "688997"
    if mock_new_code2 in initial_all:
        mock_new_code2 = "301998"

    with patch("easy_tdx.screener.universe.Path") as mock_path:
        # Mock save path so it doesn't modify real data in test unless desired
        fake_file = tmp_path / "ashares_universe.json"
        mock_path.return_value.resolve.return_value.parent.parent.parent.parent.__truediv__.return_value.__truediv__.return_value = fake_file

        added = register_new_stocks([mock_new_code1, "510300", mock_new_code1, mock_new_code2])
        assert mock_new_code1 in added
        assert mock_new_code2 in added
        assert "510300" not in added  # Invalid filtered out
        assert len(added) == 2  # Deduplicated

        # Now get_universe_symbols should include them
        updated_all = get_universe_symbols("all")
        assert mock_new_code1 in updated_all
        assert mock_new_code2 in updated_all
        assert len(updated_all) == initial_cnt + 2


def test_sync_new_stocks_mock():
    # Mock TDX client
    mock_cli = MagicMock()
    mock_cli.get_security_count.return_value = 25000

    # Mock security dataframe containing an IPO stock that does not exist in baseline
    df_sz = pd.DataFrame({
        "code": ["000001", "001901", "159915"],
        "name": ["平安银行", "全新新股", "创业板ETF"]
    })
    df_empty = pd.DataFrame(columns=["code", "name"])

    def mock_get_security_list(market, start):
        if start == 24000:
            return df_sz
        return df_empty

    mock_cli.get_security_list.side_effect = mock_get_security_list

    with patch("easy_tdx.screener.universe.register_new_stocks") as mock_register:
        mock_register.return_value = ["001901"]
        added = sync_new_stocks(cli=mock_cli)
        assert mock_register.called
        assert added == ["001901"]
