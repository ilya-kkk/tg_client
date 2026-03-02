"use client";

import { ClipboardEvent, KeyboardEvent, MouseEvent, useEffect, useRef, useState } from "react";
import styles from "./modal.module.css";

const API_BASE = "http://localhost:8000";
const PHONE_REGEX = /^\+\d{7,15}$/;

interface AddAccountModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => Promise<void> | void;
}

interface ApiMessageResponse {
  success: boolean;
  message: string;
}

interface VerifyResponse extends ApiMessageResponse {
  password_required?: boolean;
}

type Step = 1 | 2 | 3;
type LoadingAction = "send_code" | "verify_code" | "password" | null;

async function parseApiError(response: Response): Promise<string> {
  const errorBody = await response.json().catch(() => null);
  return errorBody?.detail ?? errorBody?.message ?? `Ошибка запроса (${response.status})`;
}

export default function AddAccountModal({
  isOpen,
  onClose,
  onSuccess
}: AddAccountModalProps) {
  const [step, setStep] = useState<Step>(1);
  const [sessionId, setSessionId] = useState<string>("");
  const [phone, setPhone] = useState<string>("");
  const [codeDigits, setCodeDigits] = useState<string[]>(["", "", "", "", ""]);
  const [password, setPassword] = useState<string>("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingAction, setLoadingAction] = useState<LoadingAction>(null);
  const [codeSubmitted, setCodeSubmitted] = useState(false);
  const codeRefs = useRef<Array<HTMLInputElement | null>>([]);

  const isPhoneValid = PHONE_REGEX.test(phone);
  const isLoading = loadingAction !== null;

  useEffect(() => {
    if (!isOpen) {
      setStep(1);
      setSessionId("");
      setPhone("");
      setCodeDigits(["", "", "", "", ""]);
      setPassword("");
      setShowPassword(false);
      setError(null);
      setLoadingAction(null);
      setCodeSubmitted(false);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || step !== 2 || isLoading || codeSubmitted) {
      return;
    }

    const code = codeDigits.join("");
    if (code.length !== 5) {
      return;
    }

    setCodeSubmitted(true);
    void verifyCode(code);
  }, [codeDigits, codeSubmitted, isLoading, isOpen, step]);

  useEffect(() => {
    if (isOpen && step === 2) {
      codeRefs.current[0]?.focus();
    }
  }, [isOpen, step]);

  async function sendCode() {
    if (!isPhoneValid) {
      setError("Введите номер в формате +79991234567");
      return;
    }

    const nextSessionId = crypto.randomUUID();
    setError(null);
    setLoadingAction("send_code");

    try {
      const response = await fetch(`${API_BASE}/sessions/${nextSessionId}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone })
      });

      if (!response.ok) {
        throw new Error(await parseApiError(response));
      }

      const data = (await response.json()) as ApiMessageResponse;
      if (!data.success) {
        throw new Error(data.message || "Не удалось отправить код");
      }

      setSessionId(nextSessionId);
      setStep(2);
      setCodeDigits(["", "", "", "", ""]);
      setCodeSubmitted(false);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Ошибка отправки кода");
      }
    } finally {
      setLoadingAction(null);
    }
  }

  async function verifyCode(code: string) {
    if (!sessionId) {
      setError("Сессия не инициализирована, повторите отправку кода");
      setCodeSubmitted(false);
      return;
    }

    setError(null);
    setLoadingAction("verify_code");

    try {
      const response = await fetch(`${API_BASE}/sessions/${sessionId}/auth/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, code })
      });

      if (!response.ok) {
        throw new Error(await parseApiError(response));
      }

      const data = (await response.json()) as VerifyResponse;
      if (!data.success) {
        throw new Error(data.message || "Не удалось подтвердить код");
      }

      if (data.password_required) {
        setStep(3);
        setPassword("");
        return;
      }

      await Promise.resolve(onSuccess());
      onClose();
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Ошибка подтверждения кода");
      }
      setCodeSubmitted(false);
    } finally {
      setLoadingAction(null);
    }
  }

  async function submitPassword() {
    if (!sessionId) {
      setError("Сессия не инициализирована, повторите вход");
      return;
    }
    if (!password.trim()) {
      setError("Введите пароль 2FA");
      return;
    }

    setError(null);
    setLoadingAction("password");

    try {
      const response = await fetch(`${API_BASE}/sessions/${sessionId}/auth/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password })
      });

      if (!response.ok) {
        throw new Error(await parseApiError(response));
      }

      const data = (await response.json()) as ApiMessageResponse;
      if (!data.success) {
        throw new Error(data.message || "Не удалось завершить авторизацию");
      }

      await Promise.resolve(onSuccess());
      onClose();
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Ошибка ввода пароля");
      }
    } finally {
      setLoadingAction(null);
    }
  }

  function handleCodeChange(index: number, value: string) {
    const digit = value.replace(/\D/g, "").slice(-1);

    setCodeDigits((prev) => {
      const next = [...prev];
      next[index] = digit;
      return next;
    });

    setError(null);
    setCodeSubmitted(false);

    if (digit && index < 4) {
      codeRefs.current[index + 1]?.focus();
    }
  }

  function handleCodeBackspace(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Backspace") {
      return;
    }

    if (codeDigits[index] === "" && index > 0) {
      codeRefs.current[index - 1]?.focus();
    }
  }

  function handleCodePaste(event: ClipboardEvent<HTMLInputElement>) {
    event.preventDefault();
    const pasted = event.clipboardData
      .getData("text")
      .replace(/\D/g, "")
      .slice(0, 5)
      .split("");

    if (pasted.length === 0) {
      return;
    }

    const next = ["", "", "", "", ""];
    pasted.forEach((digit, index) => {
      next[index] = digit;
    });

    setCodeDigits(next);
    setError(null);
    setCodeSubmitted(false);

    const nextFocusIndex = Math.min(pasted.length, 4);
    codeRefs.current[nextFocusIndex]?.focus();
  }

  function goBack() {
    if (isLoading) {
      return;
    }

    setError(null);

    if (step === 3) {
      setStep(2);
      setPassword("");
      return;
    }

    if (step === 2) {
      setStep(1);
      setCodeDigits(["", "", "", "", ""]);
      setCodeSubmitted(false);
    }
  }

  function onEyeMouseDown(event: MouseEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    setShowPassword(true);
  }

  function onEyeMouseUp() {
    setShowPassword(false);
  }

  function closeModal() {
    if (isLoading) {
      return;
    }
    onClose();
  }

  if (!isOpen) {
    return null;
  }

  return (
    <div className={styles.backdrop} onClick={closeModal} role="presentation">
      <div
        className={styles.modal}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Добавление аккаунта"
      >
        <button
          type="button"
          className={styles.closeButton}
          onClick={closeModal}
          aria-label="Закрыть"
          disabled={isLoading}
        >
          ×
        </button>

        <h2 className={styles.title}>Добавить аккаунт</h2>

        {step === 1 && (
          <div className={styles.stepBlock}>
            <label className={styles.label} htmlFor="phone-input">
              Номер телефона
            </label>
            <div className={styles.row}>
              <input
                id="phone-input"
                className={styles.input}
                placeholder="+79991234567"
                value={phone}
                onChange={(event) => {
                  setPhone(event.target.value.trim());
                  setError(null);
                }}
                autoComplete="tel"
              />
              <button
                type="button"
                className={styles.primaryButton}
                onClick={() => void sendCode()}
                disabled={!isPhoneValid || isLoading}
              >
                {loadingAction === "send_code" ? (
                  <span className={styles.buttonContent}>
                    <span className={styles.inlineLoader} />
                    Отправка...
                  </span>
                ) : (
                  "Отправить код"
                )}
              </button>
            </div>
            {error && <p className={styles.error}>{error}</p>}
          </div>
        )}

        {step === 2 && (
          <div className={styles.stepBlock}>
            <p className={styles.hint}>Введите 5-значный код из Telegram</p>
            <div className={styles.codeRow}>
              {codeDigits.map((digit, index) => (
                <input
                  key={index}
                  ref={(element) => {
                    codeRefs.current[index] = element;
                  }}
                  className={styles.codeInput}
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={1}
                  value={digit}
                  onChange={(event) => handleCodeChange(index, event.target.value)}
                  onKeyDown={(event) => handleCodeBackspace(index, event)}
                  onPaste={handleCodePaste}
                />
              ))}
            </div>
            <div className={styles.footerRow}>
              <button type="button" className={styles.backButton} onClick={goBack} disabled={isLoading}>
                Назад
              </button>
              {loadingAction === "verify_code" && <span className={styles.loader} />}
            </div>
            {error && <p className={styles.error}>{error}</p>}
          </div>
        )}

        {step === 3 && (
          <div className={styles.stepBlock}>
            <label className={styles.label} htmlFor="password-input">
              Пароль 2FA
            </label>
            <div className={styles.passwordWrap}>
              <input
                id="password-input"
                className={styles.input}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError(null);
                }}
                autoComplete="current-password"
              />
              <button
                type="button"
                className={styles.eyeButton}
                aria-label="Показать пароль"
                onMouseDown={onEyeMouseDown}
                onMouseUp={onEyeMouseUp}
                onMouseLeave={onEyeMouseUp}
              >
                eye
              </button>
            </div>
            <button
              type="button"
              className={styles.centerButton}
              onClick={() => void submitPassword()}
              disabled={isLoading}
            >
              {loadingAction === "password" ? (
                <span className={styles.buttonContent}>
                  <span className={styles.inlineLoader} />
                  Входим...
                </span>
              ) : (
                "Войти"
              )}
            </button>
            <button type="button" className={styles.backButton} onClick={goBack} disabled={isLoading}>
              Назад
            </button>
            {error && <p className={styles.error}>{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
