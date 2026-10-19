# -*- coding: utf-8 -*-
"""DataProvider 抽象基类。

业务层（updater / api）只依赖本接口，不直接接触任何数据源 SDK。
未来替换为 WindProvider / 其他数据源时，实现同样的方法即可，
前端与业务逻辑无需修改。
"""
from abc import ABC, abstractmethod


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_universe_constituents(self) -> list[dict]:
        """返回股票池全部成分（沪深300+创业板指+科创50，按代码去重）。
        每项: {code, ts_code, name, weight, indices, snapshot_date}"""

    @abstractmethod
    def get_latest_valuations(self) -> tuple:
        """返回 (trade_date, rows)。
        rows 每项: {code, ts_code, name, close, market_cap, pe_ttm}"""

    @abstractmethod
    def get_net_profit_yoy(self, ts_codes: set) -> list[dict]:
        """返回最新一期已披露归母净利润同比。
        每项: {code, ts_code, name, np_yoy(%), report_period, publish_date}"""

    @abstractmethod
    def get_year_first_close(self, ts_code: str, year: int):
        """返回某股票当年第一个交易日的收盘价（前复权），无数据返回 None。"""

    def get_sw_industry_map(self) -> dict:
        """返回 {code6: {'l1':..,'l2':..,'l3':..}}（可选实现，用于行业分类引导）。"""
        return {}
