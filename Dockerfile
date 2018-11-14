FROM alpine

RUN apk update && apk add python3 uwsgi-python3

RUN mkdir -pv /data/www/
COPY requirements.txt /data/www/
RUN cd /data/www; pip3 install -r requirements.txt

COPY inventory/ /data/www/inventory/
COPY inventory.ini /etc/uwsgi/conf.d/

CMD cd /data/www/; uwsgi --ini /etc/uwsgi/conf.d/inventory.ini
