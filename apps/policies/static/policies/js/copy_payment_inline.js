/**
 * Copy Payment Inline Functionality
 * 
 * Adds a "Copy" button to each payment row in the inline formset
 * on the Policy admin page. When clicked, it duplicates the row
 * with all field values copied.
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
            // Wait for Django admin to initialize the inline formsets
            setTimeout(initializeCopyButtons, 500);
            
            // Re-initialize when new rows are added
            $(document).on('formset:added', function(event, $row, formsetName) {
                if (formsetName === 'payment_schedule') {
                    addCopyButtonToRow($row);
                }
            });
        });
        
        function initializeCopyButtons() {
            // Find all payment schedule inline rows
            var $inlineGroup = $('.inline-group').filter(function() {
                return $(this).find('h2').text().indexOf('График платежей') !== -1 ||
                       $(this).find('h2').text().indexOf('Payment') !== -1;
            });
            
            if ($inlineGroup.length === 0) {
                return;
            }
            
            // Add copy button to each existing row
            $inlineGroup.find('.dynamic-payment_schedule').each(function() {
                var $row = $(this);
                if (!$row.hasClass('empty-form') && !$row.find('.copy-payment-btn').length) {
                    addCopyButtonToRow($row);
                }
            });
        }
        
        function addCopyButtonToRow($row) {
            // Skip if button already exists or if this is the empty form template
            if ($row.find('.copy-payment-btn').length || $row.hasClass('empty-form')) {
                return;
            }
            
            // Create copy button
            var $copyBtn = $('<button>', {
                type: 'button',
                class: 'copy-payment-btn',
                title: 'Копировать этот платеж',
                html: '📋 Копировать'
            });
            
            // Add click handler
            $copyBtn.on('click', function(e) {
                e.preventDefault();
                copyPaymentRow($row);
            });
            
            // Insert button at the end of the row
            var $lastCell = $row.find('td').last();
            if ($lastCell.length) {
                var $btnContainer = $('<div>', {
                    class: 'copy-payment-btn-container'
                }).append($copyBtn);
                $lastCell.append($btnContainer);
            }
        }
        
        function copyPaymentRow($sourceRow) {
            // Find the "Add another" link to trigger adding a new row
            var $inlineGroup = $sourceRow.closest('.inline-group');
            var $addButton = $inlineGroup.find('.add-row a');
            
            if ($addButton.length === 0) {
                alert('Не удалось найти кнопку добавления новой строки');
                return;
            }
            
            // Click the add button to create a new row
            $addButton.click();
            
            // Wait a bit for the new row to be created
            setTimeout(function() {
                // Find the newly added row (last non-empty row)
                var $allRows = $inlineGroup.find('.dynamic-payment_schedule').not('.empty-form');
                var $newRow = $allRows.last();
                
                if ($newRow.length === 0) {
                    alert('Не удалось создать новую строку');
                    return;
                }
                
                // Copy field values from source to new row
                copyFieldValues($sourceRow, $newRow);
                
                // Add copy button to the new row
                addCopyButtonToRow($newRow);
                
                // Scroll to the new row
                $('html, body').animate({
                    scrollTop: $newRow.offset().top - 100
                }, 500);
                
                // Highlight the new row briefly
                $newRow.addClass('payment-copied-highlight');
                setTimeout(function() {
                    $newRow.removeClass('payment-copied-highlight');
                }, 2000);
                
            }, 300);
        }
        
        function copyFieldValues($sourceRow, $targetRow) {
            // List of fields to copy
            var fieldsToCopy = [
                'year_number',
                'installment_number', 
                'due_date',
                'amount',
                'insurance_sum',
                'commission_rate',
                'kv_rub',
                'paid_date',
                'insurer_date',
                'payment_info'
            ];
            
            fieldsToCopy.forEach(function(fieldName) {
                // Find source and target inputs
                var $sourceInput = $sourceRow.find('[name$="-' + fieldName + '"]');
                var $targetInput = $targetRow.find('[name$="-' + fieldName + '"]');
                
                if ($sourceInput.length && $targetInput.length) {
                    var inputType = $sourceInput.attr('type');
                    
                    if (inputType === 'checkbox') {
                        // Copy checkbox state
                        $targetInput.prop('checked', $sourceInput.prop('checked'));
                    } else if ($sourceInput.is('select')) {
                        // Copy select value
                        $targetInput.val($sourceInput.val());
                        
                        // Trigger change event for autocomplete fields
                        if ($targetInput.hasClass('select2-hidden-accessible')) {
                            $targetInput.trigger('change.select2');
                        }
                    } else {
                        // Copy text/number/date input value
                        $targetInput.val($sourceInput.val());
                    }
                }
            });
        }
    }
    
    // Start initialization
    initWhenReady();
    
})();
