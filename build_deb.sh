#!/usr/bin/env bash
# Script para gerar pacote .deb instalável em qualquer máquina Ubuntu / Pop!_OS / Debian

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="1.3.5"
PKG_NAME="epson-projector-linux"
BUILD_DIR="${SCRIPT_DIR}/build_pkg"

echo "=== Gerando pacote .deb para ${PKG_NAME} v${VERSION} ==="

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/share/epson-projector/src"
mkdir -p "${BUILD_DIR}/usr/share/epson-projector/assets"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/64x64/apps"

# 1. Arquivo de controle DEBIAN
cat << EOF > "${BUILD_DIR}/DEBIAN/control"
Package: epson-projector-linux
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0, python3-pil, libx11-6, libxfixes3
Recommends: gir1.2-ayatanaappindicator3-0.1, fonts-noto-color-emoji
Maintainer: Open Source Community <opensource@community.org>
Description: Epson Projecao Linux
 Aplicativo nativo para controle, conexao e espelhamento
 de tela para projetores Epson na rede local sem Wine.
EOF

# 2. Script postinst (cria atalho na Área de Trabalho de todos os usuários)
cat << 'EOF' > "${BUILD_DIR}/DEBIAN/postinst"
#!/bin/bash
set -e

DESKTOP_SRC="/usr/share/applications/epson-projector.desktop"

# Procura a pasta Desktop ou Área de trabalho nos usuários de /home
for user_dir in /home/*; do
    if [ -d "$user_dir" ]; then
        user_name=$(basename "$user_dir")
        for target in "$user_dir/Desktop" "$user_dir/Área de trabalho" "$user_dir/Área de Trabalho"; do
            if [ -d "$target" ]; then
                cp -f "$DESKTOP_SRC" "$target/epson-projector.desktop"
                chown "$user_name:$user_name" "$target/epson-projector.desktop"
                chmod 755 "$target/epson-projector.desktop"
                if command -v gio >/dev/null 2>&1; then
                    su - "$user_name" -c "gio set '$target/epson-projector.desktop' metadata::trusted true" 2>/dev/null || true
                fi
            fi
        done
    fi
done

# Atualiza caches do sistema
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi

exit 0
EOF
chmod 755 "${BUILD_DIR}/DEBIAN/postinst"

# 3. Script postrm (remove atalhos do Desktop ao desinstalar)
cat << 'EOF' > "${BUILD_DIR}/DEBIAN/postrm"
#!/bin/bash
set -e

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    for user_dir in /home/*; do
        if [ -d "$user_dir" ]; then
            rm -f "$user_dir/Desktop/epson-projector.desktop" 2>/dev/null || true
            rm -f "$user_dir/Área de trabalho/epson-projector.desktop" 2>/dev/null || true
            rm -f "$user_dir/Área de Trabalho/epson-projector.desktop" 2>/dev/null || true
        fi
    done
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q || true
fi

exit 0
EOF
chmod 755 "${BUILD_DIR}/DEBIAN/postrm"

# 4. Copia arquivos de código e assets
cp "${SCRIPT_DIR}/src/"*.py "${BUILD_DIR}/usr/share/epson-projector/src/"
cp "${SCRIPT_DIR}/assets/"* "${BUILD_DIR}/usr/share/epson-projector/assets/"

# 5. Executável /usr/bin/epson-projector
cat << 'EOF' > "${BUILD_DIR}/usr/bin/epson-projector"
#!/usr/bin/env bash
export PYTHONPATH="/usr/share/epson-projector:${PYTHONPATH}"
exec python3 -u /usr/share/epson-projector/src/main.py "$@"
EOF
chmod +x "${BUILD_DIR}/usr/bin/epson-projector"

# 6. Ícone do sistema
cp "${SCRIPT_DIR}/assets/icon.png" "${BUILD_DIR}/usr/share/icons/hicolor/64x64/apps/epson-projector.png"

# 7. Atalho .desktop no sistema
cat << 'EOF' > "${BUILD_DIR}/usr/share/applications/epson-projector.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Epson Projeção Linux
GenericName=Projetor de Rede
Comment=Conexão e Espelhamento Nativo para Projetores Epson
Exec=/usr/bin/epson-projector
Icon=epson-projector
Terminal=false
Categories=Network;AudioVideo;Utility;
StartupNotify=true
EOF
chmod +x "${BUILD_DIR}/usr/share/applications/epson-projector.desktop"

# 8. Empacota com dpkg-deb
dpkg-deb --root-owner-group --build "${BUILD_DIR}" "${SCRIPT_DIR}/${PKG_NAME}_${VERSION}_all.deb"
rm -rf "${BUILD_DIR}"

echo ""
echo "✅ Pacote gerado com sucesso em:"
echo "   ${SCRIPT_DIR}/${PKG_NAME}_${VERSION}_all.deb"
echo ""
echo "Para instalar no Linux (Ubuntu / Debian / Pop!_OS / Mint):"
echo "   sudo dpkg -i ${PKG_NAME}_${VERSION}_all.deb"
echo "   sudo apt-get install -f (se faltar alguma dependência)"
