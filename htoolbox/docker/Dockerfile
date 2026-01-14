FROM nvidia/cuda:13.0.2-devel-ubuntu24.04
SHELL ["/bin/bash", "-lc"]

ARG UID=1000
ARG GID=1000
ARG UNAME=hank
ARG GNAME=hank
ARG ROOT_SHELLRC=/etc/bash.bashrc

RUN apt-get update && apt-get install -yq tzdata && \
    ln -fs /usr/share/zoneinfo/America/New_York /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata
RUN apt-get update && apt-get install -y \
    curl wget git \
    sudo linux-tools-common linux-tools-generic \
    net-tools iputils-ping iproute2 hostname iptables openssh-server openssh-client \
    htop tmux vim zip unzip\
    python3 python3-pexpect \
    g++ pkg-config make cmake ninja-build gdb \
    coreutils manpages-dev capnproto libcapnp-dev zlib1g-dev libssl-dev \
    build-essential zlib1g-dev libffi-dev libssl-dev libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev libncurses-dev tk-dev

# Create or replace the group with user specified.
RUN if getent group ${GID}; then \
        groupmod -n ${UNAME} $(getent group ${GID} | cut -d: -f1); \
    else \
        groupadd -g ${GID} ${UNAME}; \
    fi
# Create or replace the user with user specified.
RUN if getent passwd ${UID}; then \
        usermod -l ${UNAME} -g ${GID} -d /home/${UNAME} -m $(getent passwd ${UID} | cut -d: -f1); \
    else \
        useradd -u ${UID} -g ${GID} -m ${UNAME}; \
    fi
RUN usermod -aG sudo $UNAME
RUN echo "root:123456" | chpasswd
RUN echo "$UNAME:123456" | chpasswd
RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
RUN mkdir -p /opt && chown -R $UNAME /opt

RUN echo -e "\n\n"\
export HOSTNAME=\`hostname -i\` "\n"\
export HOST_ID=\`python3 -c \""print(int("\'"\${HOSTNAME}"\'".split('.')[-1])-1)"\"\` "\n"\
export NODE_ID="\${HOST_ID}" "\n" >> $ROOT_SHELLRC

############## For root ##############
# ssh
RUN curl https://raw.githubusercontent.com/RabbitWhite1/htoolbox/refs/heads/main/tmux/.tmux.conf > $HOME/.tmux.conf
RUN sed -i 's/PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
######################################

############## For $UNAME ############
USER $UNAME
ARG HOME=/home/$UNAME
ARG SHELLRC=$HOME/.bashrc

RUN mkdir -p $HOME/.local/bin
RUN echo 'export PATH=$HOME/.local/bin:$PATH' >> $SHELLRC

# uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# asdf
RUN cd /tmp && export ASDF_VERSION=0.18.0 && \
    wget "https://github.com/asdf-vm/asdf/releases/download/v${ASDF_VERSION}/asdf-v${ASDF_VERSION}-linux-amd64.tar.gz" -O /tmp/asdf.tar.gz && \
    tar xf /tmp/asdf.tar.gz && \
    mv /tmp/asdf $HOME/.local/bin/asdf
RUN echo 'export PATH="${ASDF_DATA_DIR:-$HOME/.asdf}/shims:$PATH"' >> $HOME/.bashrc
RUN echo '. <(asdf completion bash)' >> $HOME/.bashrc

RUN mkdir /opt/tiger
RUN mkdir /opt/snapshot

# Python2
RUN asdf plugin add python https://github.com/asdf-community/asdf-python.git && \
    asdf install python 2.7.18 && \
    asdf set -u python 2.7.18

# Golang
RUN asdf plugin add golang https://github.com/kennyp/asdf-golang.git && \
    asdf install golang 1.25.5 && \
    asdf set -u golang 1.25.5
RUN echo 'export PATH=`go env GOPATH`/bin:$PATH' >> ~/.bashrc

# Java
## JDK
RUN asdf plugin add java https://github.com/halcyon/asdf-java.git && \
    asdf install java openjdk-17 && \
    asdf set -u java openjdk-17
## Maven
RUN asdf plugin add maven https://github.com/halcyon/asdf-maven.git && \
    asdf install maven 3.9.4 && \
    asdf set -u maven 3.9.4

# Flamegraph
RUN git clone https://github.com/brendangregg/FlameGraph.git $HOME/FlameGraph

# etcd
ENV ETCD_UNSUPPORTED_ARCH=arm64

# Tmux
RUN curl https://raw.githubusercontent.com/RabbitWhite1/htoolbox/refs/heads/main/tmux/.tmux.conf > $HOME/.tmux.conf

# HOSTNAME: the IP address
RUN echo -e 'export HOSTNAME=`hostname -i`' >> $SHELLRC
# HOST_ID: from hostname's last octet
RUN echo -e 'export HOST_ID=$(echo $HOSTNAME | awk -F. '\''{print $NF}'\'')' >> $SHELLRC
# NODE_ID: HOST_ID - 1
RUN echo -e 'export NODE_ID=$(($HOST_ID - 1))' >> $SHELLRC
# IID: NODE_ID
RUN echo -e 'export IID=$NODE_ID' >> $SHELLRC

######################################

EXPOSE 22
ENTRYPOINT sudo service ssh start && echo `hostname -i` && source /etc/bash.bashrc && echo $IID && echo $NODE_ID && cd $HOME && bash
CMD cd $HOME && bash
