"""Auth endpoints: register, verify, login, 2FA, refresh, logout, OAuth, me."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.containers import AuthContainer
from apps.auth.dependencies import get_current_user
from apps.auth.schemas import (
    Disable2FARequest,
    Enable2FARequest,
    GoogleAuthorizeResponse,
    Login2FARequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    Setup2FAResponse,
    TokenPair,
    TwoFactorChallenge,
    VerifyEmailRequest,
)
from apps.auth.services import AuthService
from apps.auth.constants import OAUTH_COOKIE_PATH, OAUTH_STATE_COOKIE_NAME
from apps.core.database.session import session_factory
from apps.core.rate_limit import limiter
from apps.core.schemas.response import (
    APIResponse,
)
from apps.settings import app_settings
from apps.user.models import User
from apps.user.schemas import UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_metadata(request: Request) -> tuple[str | None, str | None]:
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    return user_agent, ip_address


# ----------------------------- registration --------------------------------


@router.post(
    "/register",
    response_model=APIResponse[RegisterResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("5/minute")
@inject
async def register(
    request: Request,  # noqa: ARG001 — consumed by slowapi via signature reflection
    data: RegisterRequest,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[RegisterResponse]:
    user = await auth_service.register(session, data=data)
    return APIResponse[RegisterResponse].success(
        data=RegisterResponse(user_id=user.id), message="Verification email sent."
    )


@router.post("/verify-email", response_model=APIResponse[MessageResponse])
@limiter.limit("10/minute")
@inject
async def verify_email(
    request: Request,  # noqa: ARG001 — consumed by slowapi via signature reflection
    data: VerifyEmailRequest,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[MessageResponse]:
    await auth_service.verify_email(session, email=data.email, code=data.code)
    return APIResponse[MessageResponse].success(
        data=MessageResponse(message="Email verified."), message="Email verified successfully."
    )


@router.post(
    "/verify-email/resend",
    response_model=APIResponse[MessageResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("5/minute")
@inject
async def resend_verification(
    request: Request,  # noqa: ARG001 — consumed by slowapi via signature reflection
    data: ResendVerificationRequest,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[MessageResponse]:
    await auth_service.resend_verification(session, email=data.email)
    return APIResponse[MessageResponse].success(
        data=MessageResponse(message="If the email exists, a new code has been sent."),
        message="Verification email sent.",
    )


# ----------------------------- login flows ---------------------------------


@router.post(
    "/login",
    response_model=APIResponse[TokenPair | TwoFactorChallenge],
)
@limiter.limit("5/minute")
@inject
async def login(
    data: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[TokenPair | TwoFactorChallenge]:
    user_agent, ip_address = _client_metadata(request)
    result = await auth_service.login(session, data=data, user_agent=user_agent, ip_address=ip_address)
    return APIResponse[TokenPair | TwoFactorChallenge].success(
        data=result,
        message="Two-factor required." if isinstance(result, TwoFactorChallenge) else "Logged in.",
    )


@router.post("/login/2fa", response_model=APIResponse[TokenPair])
@limiter.limit("10/minute")
@inject
async def login_2fa(
    data: Login2FARequest,
    request: Request,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[TokenPair]:
    user_agent, ip_address = _client_metadata(request)
    pair = await auth_service.login_2fa(
        session,
        challenge_token=data.challenge_token,
        totp_code=data.totp_code,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    return APIResponse[TokenPair].success(data=pair, message="Logged in.")


# ----------------------------- token lifecycle -----------------------------


@router.post("/refresh", response_model=APIResponse[TokenPair])
@limiter.limit("30/minute")
@inject
async def refresh(
    data: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[TokenPair]:
    user_agent, ip_address = _client_metadata(request)
    pair = await auth_service.refresh(
        session,
        raw_refresh_token=data.refresh_token,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    return APIResponse[TokenPair].success(data=pair, message="Token refreshed.")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def logout(
    data: LogoutRequest,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> Response:
    await auth_service.logout(session, raw_refresh_token=data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------- me --------------------------------------


@router.get("/me", response_model=APIResponse[UserResponse])
async def me(
    current_user: User = Depends(get_current_user),
) -> APIResponse[UserResponse]:
    return APIResponse[UserResponse].success(
        data=UserResponse.model_validate(current_user), message="User retrieved successfully."
    )


# --------------------------------- 2FA -------------------------------------


@router.post("/2fa/setup", response_model=APIResponse[Setup2FAResponse])
@inject
async def setup_2fa(
    session: AsyncSession = Depends(session_factory),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[Setup2FAResponse]:
    setup = await auth_service.setup_2fa(session, user=current_user)
    return APIResponse[Setup2FAResponse].success(data=setup, message="2FA setup initiated.")


@router.post("/2fa/enable", response_model=APIResponse[MessageResponse])
@inject
async def enable_2fa(
    data: Enable2FARequest,
    session: AsyncSession = Depends(session_factory),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[MessageResponse]:
    await auth_service.enable_2fa(session, user=current_user, totp_code=data.totp_code)
    return APIResponse[MessageResponse].success(
        data=MessageResponse(message="2FA enabled."), message="Two-factor authentication enabled."
    )


@router.post("/2fa/disable", response_model=APIResponse[MessageResponse])
@limiter.limit("5/minute")
@inject
async def disable_2fa(
    request: Request,  # noqa: ARG001 — consumed by slowapi via signature reflection
    data: Disable2FARequest,
    session: AsyncSession = Depends(session_factory),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[MessageResponse]:
    await auth_service.disable_2fa(
        session,
        user=current_user,
        password=data.password,
        totp_code=data.totp_code,
    )
    return APIResponse[MessageResponse].success(
        data=MessageResponse(message="2FA disabled."), message="Two-factor authentication disabled."
    )


# ------------------------------- Google OAuth ------------------------------


def _is_production() -> bool:
    return app_settings.environment.lower() == "production"


@router.get(
    "/oauth/google/authorize",
    response_model=APIResponse[GoogleAuthorizeResponse],
)
@inject
async def google_authorize(
    response: Response,
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[GoogleAuthorizeResponse]:
    flow = auth_service.start_google_oauth()
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=flow.state_id,
        max_age=app_settings.auth.oauth_state_expire_minutes * 60,
        httponly=True,
        secure=_is_production(),
        samesite="lax",
        path=OAUTH_COOKIE_PATH,
    )
    return APIResponse[GoogleAuthorizeResponse].success(
        data=GoogleAuthorizeResponse(authorize_url=flow.authorize_url, state=flow.state_token),
        message="Google authorization URL generated.",
    )


@router.get(
    "/oauth/google/callback",
    response_model=APIResponse[TokenPair | TwoFactorChallenge],
)
@limiter.limit("10/minute")
@inject
async def google_callback(
    code: str,
    state: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> APIResponse[TokenPair | TwoFactorChallenge]:
    user_agent, ip_address = _client_metadata(request)
    cookie_state_id = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    try:
        result = await auth_service.google_callback(
            session,
            code=code,
            state=state,
            cookie_state_id=cookie_state_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
    finally:
        response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path=OAUTH_COOKIE_PATH)
    return APIResponse[TokenPair | TwoFactorChallenge].success(
        data=result,
        message="Two-factor required." if isinstance(result, TwoFactorChallenge) else "Logged in via Google.",
    )
