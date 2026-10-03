/**
 * Клиент API: хранит токены, обновляет access-токен и прячет детали ошибок.
 */

const API_BASE = '/api/v1';
const ACCESS_KEY = 'bank_access_token';
const REFRESH_KEY = 'bank_refresh_token';

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY);
  },
  save(payload) {
    localStorage.setItem(ACCESS_KEY, payload.access_token);
    localStorage.setItem(REFRESH_KEY, payload.refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

/**
 * Ошибка API с кодом ответа и сообщением для пользователя.
 */
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * Разобрать тело ошибки и вытащить текст для пользователя.
 *
 * @param {Response} response - ответ с ошибкой
 * @returns {Promise<string>} текст ошибки
 */
async function readError(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === 'string') {
      return data.detail;
    }
    // Ошибка валидатора — список объектов, берём первую проблему.
    if (Array.isArray(data.detail) && data.detail.length > 0) {
      const first = data.detail[0];
      return `${first.loc?.slice(-1)[0] ?? 'поле'}: ${first.msg}`;
    }
    return `Ошибка ${response.status}`;
  } catch {
    return `Ошибка ${response.status}`;
  }
}

/**
 * Выполнить запрос к API.
 *
 * @param {string} path - путь относительно /api/v1
 * @param {object} options - параметры fetch
 * @param {boolean} retry - разрешить один повтор после обновления токена
 * @returns {Promise<any>} разобранное тело ответа
 */
async function request(path, options = {}, retry = true) {
  const headers = { ...(options.headers || {}) };
  const access = tokens.access;

  if (access) {
    headers.Authorization = `Bearer ${access}`;
  }
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    body:
      options.body !== undefined && !(options.body instanceof FormData)
        ? JSON.stringify(options.body)
        : options.body,
  });

  if (response.status === 401 && retry && tokens.refresh) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return request(path, options, false);
    }
  }

  if (!response.ok) {
    const detail = await readError(response);
    if (response.status === 401) {
      tokens.clear();
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

/**
 * Обновить access-токен по refresh-токену.
 *
 * @returns {Promise<boolean>} удалось ли обновить
 */
async function tryRefresh() {
  try {
    const payload = await request(
      '/auth/refresh',
      { method: 'POST', body: { refresh_token: tokens.refresh } },
      false,
    );
    tokens.save(payload);
    return true;
  } catch {
    tokens.clear();
    return false;
  }
}

export const api = {
  register: (data) =>
    request('/auth/register', { method: 'POST', body: data }),
  login: (data) => request('/auth/login', { method: 'POST', body: data }),
  me: () => request('/auth/me'),

  listAccounts: () => request('/accounts'),
  createAccount: (data) => request('/accounts', { method: 'POST', body: data }),
  getBalance: (id) => request(`/accounts/${id}/balance`),

  /**
   * Создать перевод с ключом идемпотентности.
   *
   * @param {object} data - параметры перевода
   * @returns {Promise<any>} созданная транзакция
   */
  createTransaction: (data) => {
    // Ключ генерируется на стороне клиента: повтор запроса с тем же
    // ключом не спишет деньги дважды.
    const key =
      window.crypto && typeof window.crypto.randomUUID === 'function'
        ? window.crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

    return request('/transactions', {
      method: 'POST',
      body: data,
      headers: { 'Idempotency-Key': key },
    });
  },

  listTransactions: (params = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        query.append(key, value);
      }
    });
    const suffix = query.toString();
    return request(`/transactions${suffix ? `?${suffix}` : ''}`);
  },
};