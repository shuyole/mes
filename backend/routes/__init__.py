# -*- coding: utf-8 -*-
"""业务 API 蓝图汇总与注册模块。"""

from routes.auth import auth_bp
from routes.orders import orders_bp
from routes.line import line_bp
from routes.scada import scada_bp
from routes.production import production_bp
from routes.system import system_bp


def register_routes(app):
    """把全部 6 个业务蓝图一键注册到 Flask 应用实例中。"""
    app.register_blueprint(auth_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(line_bp)
    app.register_blueprint(scada_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(system_bp)


__all__ = [
    "register_routes",
    "auth_bp",
    "orders_bp",
    "line_bp",
    "scada_bp",
    "production_bp",
    "system_bp",
]
