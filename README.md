# Cortes

Um vídeo por vez, na VPS. O arquivo entra, o ffmpeg abre janelas de cerca de 50 segundos nas pausas, o faster-whisper `small` em CPU int8 legenda em português, e o clipe sai em 720×1280.

A publicação nas redes continua no Cast. Este serviço só corta e legenda, para não misturar o modelo com o worker que já publica.

Limites de propósito: 2 threads, um job na fila, no máximo 80 clipes, upload até 1500 MB. O arquivo original é apagado quando os clipes ficam prontos. Clipes somem 48 horas depois.

O repositório é público para o Dokploy clonar sem chave, no mesmo esquema do Cast. O token de acesso fica só na variável `TOKEN` do servidor.
