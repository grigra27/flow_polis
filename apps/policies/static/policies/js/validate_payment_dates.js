/**
 * Payment Schedule Date Validation
 *
 * Validates payment dates before saving to ensure that payments with the same
 * installment_number across different years follow a consistent yearly pattern.
 * Shows a warning if dates deviate from the expected pattern.
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
            // Intercept form submission
            $('form').on('submit', function(e) {
                var validationResult = validatePaymentDates();

                if (!validationResult.isValid) {
                    e.preventDefault();
                    showValidationWarning(validationResult.warnings, function(confirmed) {
                        if (confirmed) {
                            // User confirmed, submit the form without validation
                            $('form').off('submit').submit();
                        }
                    });
                    return false;
                }
            });
        });

        function validatePaymentDates() {
            var result = {
                isValid: true,
                warnings: []
            };

            // Find all payment schedule rows
            var $inlineGroup = $('.inline-group').filter(function() {
                return $(this).find('h2').text().indexOf('График платежей') !== -1 ||
                       $(this).find('h2').text().indexOf('Payment') !== -1;
            });

            if ($inlineGroup.length === 0) {
                return result;
            }

            // Collect all payment data
            var payments = [];
            $inlineGroup.find('.dynamic-payment_schedule').not('.empty-form').each(function() {
                var $row = $(this);

                // Skip deleted rows
                var $deleteCheckbox = $row.find('input[name$="-DELETE"]');
                if ($deleteCheckbox.length && $deleteCheckbox.prop('checked')) {
                    return;
                }

                var yearNumber = parseInt($row.find('[name$="-year_number"]').val());
                var installmentNumber = parseInt($row.find('[name$="-installment_number"]').val());
                var dueDateStr = $row.find('[name$="-due_date"]').val();

                // Skip if any required field is missing
                if (!yearNumber || !installmentNumber || !dueDateStr) {
                    return;
                }

                var dueDate = parseDate(dueDateStr);
                if (!dueDate) {
                    return;
                }

                payments.push({
                    yearNumber: yearNumber,
                    installmentNumber: installmentNumber,
                    dueDate: dueDate,
                    dueDateStr: dueDateStr
                });
            });

            // Need at least 2 payments to validate pattern
            if (payments.length < 2) {
                return result;
            }

            // Group payments by installment_number
            var paymentsByInstallment = {};
            payments.forEach(function(payment) {
                if (!paymentsByInstallment[payment.installmentNumber]) {
                    paymentsByInstallment[payment.installmentNumber] = [];
                }
                paymentsByInstallment[payment.installmentNumber].push(payment);
            });

            // Validate each installment group
            Object.keys(paymentsByInstallment).forEach(function(installmentNumber) {
                var group = paymentsByInstallment[installmentNumber];

                // Need at least 2 payments in group to validate
                if (group.length < 2) {
                    return;
                }

                // Sort by year_number
                group.sort(function(a, b) {
                    return a.yearNumber - b.yearNumber;
                });

                // Check for inconsistencies
                var inconsistencies = findDateInconsistencies(group);
                if (inconsistencies.length > 0) {
                    result.isValid = false;
                    result.warnings.push({
                        installmentNumber: installmentNumber,
                        inconsistencies: inconsistencies,
                        payments: group
                    });
                }
            });

            return result;
        }

        function findDateInconsistencies(payments) {
            var inconsistencies = [];

            // Check each payment against the previous one
            for (var i = 1; i < payments.length; i++) {
                var prev = payments[i - 1];
                var curr = payments[i];

                // Calculate expected date (previous date + year difference)
                var yearDiff = curr.yearNumber - prev.yearNumber;
                var expectedDate = new Date(prev.dueDate);
                expectedDate.setFullYear(expectedDate.getFullYear() + yearDiff);

                // Check if current date matches expected date
                var daysDiff = Math.abs(daysBetween(curr.dueDate, expectedDate));

                // Allow 3 days tolerance for leap years and edge cases
                if (daysDiff > 3) {
                    inconsistencies.push({
                        yearNumber: curr.yearNumber,
                        actualDate: curr.dueDateStr,
                        expectedDate: formatDate(expectedDate),
                        previousYear: prev.yearNumber,
                        previousDate: prev.dueDateStr,
                        daysDiff: daysDiff
                    });
                }
            }

            return inconsistencies;
        }

        function showValidationWarning(warnings, callback) {
            var message = 'Обнаружены несоответствия в датах платежей:\n\n';

            warnings.forEach(function(warning) {
                message += 'Платеж №' + warning.installmentNumber + ':\n';

                warning.payments.forEach(function(payment, index) {
                    message += '  Год ' + payment.yearNumber + ': ' + payment.dueDateStr;

                    if (index > 0) {
                        var prev = warning.payments[index - 1];
                        var yearDiff = payment.yearNumber - prev.yearNumber;
                        message += ' (разница: ' + yearDiff + ' год';
                        if (yearDiff > 1 || yearDiff === 0) {
                            message += 'а';
                        }
                        message += ')';
                    }
                    message += '\n';
                });

                if (warning.inconsistencies.length > 0) {
                    message += '\n  Ожидаемые даты:\n';
                    warning.inconsistencies.forEach(function(inc) {
                        message += '  Год ' + inc.yearNumber + ': ' + inc.expectedDate +
                                   ' (указано: ' + inc.actualDate + ')\n';
                    });
                }

                message += '\n';
            });

            message += 'Вы уверены, что хотите сохранить эти данные?';

            var confirmed = confirm(message);
            callback(confirmed);
        }

        function parseDate(dateStr) {
            // Try to parse date in various formats
            // Django admin uses YYYY-MM-DD format
            var parts = dateStr.split('-');
            if (parts.length === 3) {
                var year = parseInt(parts[0]);
                var month = parseInt(parts[1]) - 1; // JS months are 0-indexed
                var day = parseInt(parts[2]);
                return new Date(year, month, day);
            }

            // Try DD.MM.YYYY format
            parts = dateStr.split('.');
            if (parts.length === 3) {
                var day = parseInt(parts[0]);
                var month = parseInt(parts[1]) - 1;
                var year = parseInt(parts[2]);
                return new Date(year, month, day);
            }

            return null;
        }

        function formatDate(date) {
            var day = ('0' + date.getDate()).slice(-2);
            var month = ('0' + (date.getMonth() + 1)).slice(-2);
            var year = date.getFullYear();
            return day + '.' + month + '.' + year;
        }

        function daysBetween(date1, date2) {
            var oneDay = 24 * 60 * 60 * 1000; // milliseconds in a day
            return Math.round((date1.getTime() - date2.getTime()) / oneDay);
        }
    }

    // Start initialization
    initWhenReady();

})();
