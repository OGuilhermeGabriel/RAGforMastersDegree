window.APP_CONFIG = {
  API_BASE_URL:
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
      ? "http://localhost:8000/api/v1"
      : "https://api.guilhermegabriel.grupo-05.sd.ufersa.dev.br/api/v1",
};
