from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Admin do Django (acessível em /admin/)
    path('admin/', admin.site.urls),

    # App SIRESP (login, logout, config, etc)
    path('', include('siresp_app.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)