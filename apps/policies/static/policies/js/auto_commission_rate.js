/**
 * Auto Commission Rate Functionality
 *
 * Automatically calculates kv_rub (commission in rubles) in payment schedule inline
 * based on selected insurer and insurance_type in the main Policy form.
 * The commission_rate field is now hidden and stored in the database.
 */

(function() {
    'use strict';

    // Wait for django.jQuery to be available
    function initWhenReady() {
        if (typeof django === 'undefined' || typeof django.jQuery === 'undefined') {
            setTimeout(initWhenReady, 100);
            return;
        }

        var $ = django.jQuery;

        $(document).ready(function() {
            initAutoCommissionRate();
        });

        function initAutoCommissionRate() {
            // Find insurer and insurance_type fields in the main form
            var $insurerField = $('#id_insurer');
            var $insuranceTypeField = $('#id_insurance_type');

            if ($insurerField.length === 0 || $insuranceTypeField.length === 0) {
                console.log('Поля страховщика или вида страхования не найдены');
                return;
            }

            // Add change handlers
            $insurerField.on('change', function() {
                updateCommissionRates();
            });

            $insuranceTypeField.on('change', function() {
                updateCommissionRates();
            });

            // Also handle when new payment rows are added
            $(document).on('formset:added', function(event, $row, formsetName) {
                if (formsetName === 'payment_schedule') {
                    // Apply commission rate to the new row
                    updateCommissionRates();
                }
            });
        }

        function updateCommissionRates() {
            var $insurerField = $('#id_insurer');
            var $insuranceTypeField = $('#id_insurance_type');

            var insurerId = $insurerField.val();
            var insuranceTypeId = $insuranceTypeField.val();

            // Both fields must be selected
            if (!insurerId || !insuranceTypeId) {
                console.log('Не выбран страховщик или вид страхования');
                return;
            }

            // Make AJAX request to get commission rate
            $.ajax({
                url: '/insurers/api/commission-rate/',
                method: 'GET',
                data: {
                    insurer_id: insurerId,
                    insurance_type_id: insuranceTypeId
                },
                success: function(response) {
                    if (response.success) {
                        applyCommissionRateToAllRows(
                            response.commission_rate_id,
                            response.kv_percent,
                            response.display_name
                        );
                    } else {
                        console.warn('Ставка комиссии не найдена:', response.error);
                        showNotification('warning', response.error);
                    }
                },
                error: function(xhr, status, error) {
                    console.error('Ошибка при получении ставки комиссии:', error);
                    showNotification('error', 'Ошибка при получении ставки комиссии');
                }
            });
        }

        function applyCommissionRateToAllRows(commissionRateId, kvPercent, displayName) {
            // Find all payment schedule rows
            var $inlineGroup = $('.inline-group').filter(function() {
                return $(this).find('h2').text().indexOf('График платежей') !== -1 ||
                       $(this).find('h2').text().indexOf('Payment') !== -1;
            });

            if ($inlineGroup.length === 0) {
                return;
            }

            var updatedCount = 0;

            // Update each row
            $inlineGroup.find('.dynamic-payment_schedule').each(function() {
                var $row = $(this);

                // Skip empty form template and deleted rows
                if ($row.hasClass('empty-form') || $row.find('input[name$="-DELETE"]').prop('checked')) {
                    return;
                }

                // Find hidden commission_rate field and set its value
                var $commissionRateField = $row.find('input[name$="-commission_rate"]');
                if ($commissionRateField.length > 0) {
                    $commissionRateField.val(commissionRateId);
                }

                // Recalculate kv_rub for this row
                recalculateKvRub($row, kvPercent);

                updatedCount++;
            });

            if (updatedCount > 0) {
                showNotification('success',
                    'Комиссия пересчитана для ' + updatedCount + ' платеж(ей): ' + displayName
                );
            }
        }

        function recalculateKvRub($row, kvPercent) {
            // Find amount and kv_rub fields
            var $amountField = $row.find('input[name$="-amount"]');
            var $kvRubField = $row.find('input[name$="-kv_rub"]');

            if ($amountField.length === 0 || $kvRubField.length === 0) {
                return;
            }

            var amount = parseFloat($amountField.val());
            var kvPercentValue = parseFloat(kvPercent);

            if (isNaN(amount) || isNaN(kvPercentValue)) {
                return;
            }

            // Calculate commission in rubles
            var kvRub = (amount * kvPercentValue / 100).toFixed(2);
            $kvRubField.val(kvRub);
        }

        function showNotification(type, message) {
            // Create notification element
            var $notification = $('<div>', {
                class: 'commission-rate-notification commission-rate-notification-' + type,
                html: message
            });

            // Add to page
            var $container = $('.breadcrumbs');
            if ($container.length === 0) {
                $container = $('body');
            }

            $container.after($notification);

            // Auto-hide after 5 seconds
            setTimeout(function() {
                $notification.fadeOut(function() {
                    $(this).remove();
                });
            }, 5000);
        }
    }

    // Start initialization
    initWhenReady();

})();
