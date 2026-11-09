# syntax=docker/dockerfile:1
# check=error=true

ARG DOCKER_IMAGE=alpine:3.24
FROM $DOCKER_IMAGE AS dev

ENV LUAJIT_VERSION=v2.1

RUN apk add --no-cache git build-base cmake curl-dev zlib-dev zstd-dev \
		sqlite-dev postgresql-dev hiredis-dev leveldb-dev \
		gmp-dev jsoncpp-dev ninja

WORKDIR /usr/src/

ADD https://github.com/jupp0r/prometheus-cpp.git#b9366fc3b28292e553ce4820c8929287cdf8e04d /usr/src/prometheus-cpp
ADD https://github.com/libspatialindex/libspatialindex.git?branch=main /usr/src/libspatialindex
ADD --keep-git-dir https://luajit.org/git/luajit.git?branch=${LUAJIT_VERSION} /usr/src/luajit

RUN cd prometheus-cpp && \
		cmake -B build \
			-DCMAKE_INSTALL_PREFIX=/usr/local \
			-DCMAKE_BUILD_TYPE=Release \
			-DENABLE_TESTING=0 \
			-GNinja && \
		cmake --build build && \
		cmake --install build && \
		cd /usr/src/ && \
	cd libspatialindex && \
		cmake -B build \
			-DCMAKE_INSTALL_PREFIX=/usr/local && \
		cmake --build build && \
		cmake --install build && \
		cd /usr/src/ && \
	cd luajit && \
		make amalg && make install && \
	cd /usr/src/

FROM dev AS builder

COPY .git /usr/src/deepforge/.git
COPY CMakeLists.txt /usr/src/deepforge/CMakeLists.txt
COPY README.md /usr/src/deepforge/README.md
COPY LICENSE.txt COPYING.LESSER THIRD_PARTY_NOTICES.md /usr/src/deepforge/
COPY minetest.conf.example /usr/src/deepforge/minetest.conf.example
COPY builtin /usr/src/deepforge/builtin
COPY cmake /usr/src/deepforge/cmake
COPY doc /usr/src/deepforge/doc
COPY fonts /usr/src/deepforge/fonts
COPY lib /usr/src/deepforge/lib
COPY misc /usr/src/deepforge/misc
COPY po /usr/src/deepforge/po
COPY src /usr/src/deepforge/src
COPY irr /usr/src/deepforge/irr
COPY textures /usr/src/deepforge/textures

WORKDIR /usr/src/deepforge
RUN cmake -B build \
		-DCMAKE_INSTALL_PREFIX=/usr/local \
		-DCMAKE_BUILD_TYPE=Release \
		-DBUILD_SERVER=TRUE \
		-DENABLE_PROMETHEUS=TRUE -DENABLE_LEVELDB=FALSE -DENABLE_POSTGRESQL=FALSE -DENABLE_REDIS=FALSE \
		-DBUILD_UNITTESTS=FALSE -DBUILD_BENCHMARKS=FALSE \
		-DBUILD_CLIENT=FALSE \
		-GNinja && \
	cmake --build build && \
	cmake --install build

FROM $DOCKER_IMAGE AS runtime

RUN apk add --no-cache curl gmp libstdc++ libgcc libpq jsoncpp zstd-libs \
				sqlite-libs postgresql hiredis leveldb && \
	adduser -D minetest --uid 30000 -h /var/lib/minetest && \
	chown -R minetest:minetest /var/lib/minetest

WORKDIR /var/lib/minetest

COPY --from=builder /usr/local/share/deepforge /usr/local/share/deepforge
COPY --from=builder /usr/local/bin/deepforgeserver /usr/local/bin/deepforgeserver
COPY --from=builder /usr/local/share/doc/deepforge/minetest.conf.example /etc/minetest/minetest.conf
COPY --from=builder /usr/local/lib/libspatialindex* /usr/local/lib/
COPY --from=builder /usr/local/lib/libluajit* /usr/local/lib/
USER minetest:minetest

EXPOSE 30000/udp 30000/tcp
VOLUME /var/lib/minetest/ /etc/minetest/

ENTRYPOINT ["/usr/local/bin/deepforgeserver"]
CMD ["--config", "/etc/minetest/minetest.conf"]
