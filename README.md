PATÁN V1

Ajuste exclusivo de la segunda puerta de acceso:
- lienzo aprobado con panel PIN de cuatro casilleros;
- PIN funcional superpuesto y alineado con los cuatro casilleros;
- flecha funcional alineada con el lienzo;
- ayudas/contador del campo ocultos para mantener el diseño limpio.

El resto de PATÁN permanece sin cambios.

## Streamlit Cloud + Supabase
En Streamlit > App settings > Secrets agregar:

DATABASE_URL = "postgresql://postgres.PROJECT_REF:TU_PASSWORD@HOST_POOLER:6543/postgres?sslmode=require"

Usar la URI de Supabase > Connect > Direct > Transaction pooler y reemplazar [YOUR-PASSWORD].
No subir esta URI ni la contraseña a GitHub.
