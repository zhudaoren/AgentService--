class AppException(Exception):
    """应用异常基类"""

    code: int = 9999
    message: str = "内部错误"
    status_code: int = 500

    def __init__(self, message: str = "", code: int = 0, status_code: int = 0):
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        super().__init__(self.message)


class NotFoundException(AppException):
    code = 4040
    message = "资源不存在"
    status_code = 404


class ValidationException(AppException):
    code = 1001
    message = "参数校验失败"
    status_code = 400


class UnauthorizedException(AppException):
    code = 4010
    message = "未授权访问"
    status_code = 401


class BadRequestException(AppException):
    code = 4000
    message = "请求错误"
    status_code = 400


class LLMException(AppException):
    code = 9001
    message = "LLM调用失败"
    status_code = 500
