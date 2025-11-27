# Migration to convert leasing_manager from CharField to ForeignKey

from django.db import migrations, models
import django.db.models.deletion


def migrate_leasing_managers_forward(apps, schema_editor):
    """
    Миграция данных:
    1. Создаем менеджеров из существующих уникальных значений
    2. Создаем менеджера "Не указан" для пустых значений
    3. Связываем полисы с соответствующими менеджерами
    """
    Policy = apps.get_model('policies', 'Policy')
    LeasingManager = apps.get_model('insurers', 'LeasingManager')
    
    # Создаем менеджера "Не указан" для пустых значений
    default_manager, _ = LeasingManager.objects.get_or_create(
        name='Не указан',
        defaults={'notes': 'Менеджер по умолчанию для полисов без указанного менеджера'}
    )
    
    # Получаем все уникальные значения менеджеров из существующих полисов
    unique_managers = Policy.objects.exclude(
        leasing_manager=''
    ).values_list('leasing_manager', flat=True).distinct()
    
    # Создаем записи для каждого уникального менеджера
    manager_mapping = {}
    for manager_name in unique_managers:
        if manager_name and manager_name.strip():
            manager, _ = LeasingManager.objects.get_or_create(
                name=manager_name.strip()
            )
            manager_mapping[manager_name] = manager
    
    # Обновляем полисы: связываем с новыми записями менеджеров
    for policy in Policy.objects.all():
        if policy.leasing_manager and policy.leasing_manager.strip():
            policy.leasing_manager_new = manager_mapping.get(
                policy.leasing_manager,
                default_manager
            )
        else:
            policy.leasing_manager_new = default_manager
        policy.save(update_fields=['leasing_manager_new'])


def migrate_leasing_managers_backward(apps, schema_editor):
    """
    Обратная миграция: восстанавливаем текстовые значения из связанных менеджеров
    """
    Policy = apps.get_model('policies', 'Policy')
    
    for policy in Policy.objects.all():
        if policy.leasing_manager_new:
            # Не восстанавливаем "Не указан" как текст
            if policy.leasing_manager_new.name != 'Не указан':
                policy.leasing_manager = policy.leasing_manager_new.name
            else:
                policy.leasing_manager = ''
        policy.save(update_fields=['leasing_manager'])


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0006_policy_policies_po_policy__44a6bf_idx'),
        ('insurers', '0007_leasingmanager'),
    ]

    operations = [
        # Шаг 1: Добавляем новое поле ForeignKey (временное)
        migrations.AddField(
            model_name='policy',
            name='leasing_manager_new',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='policies',
                to='insurers.leasingmanager',
                verbose_name='Менеджер лизинговой компании'
            ),
        ),
        
        # Шаг 2: Мигрируем данные
        migrations.RunPython(
            migrate_leasing_managers_forward,
            migrate_leasing_managers_backward
        ),
        
        # Шаг 3: Удаляем старое поле
        migrations.RemoveField(
            model_name='policy',
            name='leasing_manager',
        ),
        
        # Шаг 4: Переименовываем новое поле в старое имя
        migrations.RenameField(
            model_name='policy',
            old_name='leasing_manager_new',
            new_name='leasing_manager',
        ),
    ]
