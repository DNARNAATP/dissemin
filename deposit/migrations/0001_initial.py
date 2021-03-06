# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('upload', '0002_uploadedpdf_num_pages'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('papers', '0009_empty'),
    ]

    operations = [
        migrations.CreateModel(
            name='DepositRecord',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('request', models.TextField(null=True, blank=True)),
                ('identifier', models.CharField(max_length=512, null=True, blank=True)),
                ('pdf_url', models.URLField(max_length=1024, null=True, blank=True)),
                ('date', models.DateTimeField(auto_now=True)),
                ('upload_type', models.FileField(upload_to='deposits')),
                ('file', models.ForeignKey(to='upload.UploadedPDF')),
                ('paper', models.ForeignKey(to='papers.Paper')),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'papers_depositrecord',
            },
            bases=(models.Model,),
        ),
    ]
