/**
 * Auto-copy client (lessee) to policyholder field
 *
 * Automatically copies the selected lessee to the policyholder field
 * when the lessee is changed, but only if policyholder is empty.
 * This helps reduce data entry since in 99% of cases they are the same.
 */

// Wait for Django admin jQuery to be available
(function() {
    'use strict';

    var initialized = false; // Flag to prevent double initialization

    function initAutoCopy() {
        // Use django.jQuery if available, otherwise use window.jQuery
        var $ = django.jQuery || window.jQuery;

        if (!$) {
            console.error('jQuery not found!');
            return;
        }

        // Prevent double initialization
        if (initialized) {
            console.log('Auto-copy policyholder: Already initialized, skipping');
            return;
        }

        console.log('Auto-copy policyholder: Initializing...');

        // Get the client (lessee) and policyholder select elements
        var $clientSelect = $('#id_client');
        var $policyholderSelect = $('#id_policyholder');

        console.log('Client select found:', $clientSelect.length);
        console.log('Policyholder select found:', $policyholderSelect.length);

        if ($clientSelect.length && $policyholderSelect.length) {
            // Check if help text already exists
            var $existingHelp = $('.auto-copy-help');
            if ($existingHelp.length === 0) {
                // Add a visual indicator that auto-copy is active
                var $helpText = $('<div class="help auto-copy-help">')
                    .html('💡 Страхователь автоматически копируется из лизингополучателя. Вы можете изменить его вручную при необходимости.')
                    .css({
                        'color': '#666',
                        'font-size': '12px',
                        'margin-top': '5px',
                        'font-style': 'italic',
                        'padding': '5px 10px',
                        'background-color': '#e3f2fd',
                        'border-left': '3px solid #2196f3',
                        'border-radius': '3px'
                    });

                // Find the field wrapper and add help text
                var $policyholderWrapper = $policyholderSelect.closest('.form-row');
                if ($policyholderWrapper.length) {
                    $policyholderWrapper.append($helpText);
                }
            }

            // Function to copy client to policyholder
            function copyClientToPolicyholder() {
                var clientValue = $clientSelect.val();
                console.log('Copying client value:', clientValue);

                // Only copy if client has a value
                if (clientValue) {
                    // For autocomplete fields (Select2), we need to handle differently
                    // First, set the value
                    $policyholderSelect.val(clientValue);

                    // Trigger change event to update Select2 and any dependent fields
                    $policyholderSelect.trigger('change');

                    // If using Select2, also trigger select2:select event
                    if ($.fn.select2 && $policyholderSelect.hasClass('select2-hidden-accessible')) {
                        console.log('Triggering Select2 update');
                        // Get the text from client select
                        var clientText = $clientSelect.find('option:selected').text();

                        // Create a new option if it doesn't exist
                        if ($policyholderSelect.find("option[value='" + clientValue + "']").length === 0) {
                            var newOption = new Option(clientText, clientValue, true, true);
                            $policyholderSelect.append(newOption);
                        }

                        $policyholderSelect.val(clientValue).trigger('change');
                    }

                    // Visual feedback
                    var $select2Container = $policyholderSelect.next('.select2-container');
                    if ($select2Container.length) {
                        $select2Container.find('.select2-selection').css('background-color', '#e8f5e9');
                        setTimeout(function() {
                            $select2Container.find('.select2-selection').css('background-color', '');
                        }, 1000);
                    } else {
                        $policyholderSelect.css('background-color', '#e8f5e9');
                        setTimeout(function() {
                            $policyholderSelect.css('background-color', '');
                        }, 1000);
                    }

                    console.log('Value copied successfully');
                }
            }

            // Auto-copy when client changes
            $clientSelect.on('change', function() {
                console.log('Client changed, copying to policyholder');
                copyClientToPolicyholder();
            });

            // If this is a new policy (both fields empty), copy on page load if client is set
            if (!$policyholderSelect.val() && $clientSelect.val()) {
                console.log('Initial copy on page load');
                copyClientToPolicyholder();
            }

            // Mark as initialized
            initialized = true;
            console.log('Auto-copy policyholder: Initialized successfully');
        } else {
            console.log('Auto-copy policyholder: Fields not found');
        }
    }

    // Try to initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            console.log('DOMContentLoaded, initializing auto-copy');
            // Wait a bit for Django admin to fully load
            setTimeout(initAutoCopy, 100);
        });
    } else {
        // DOM already loaded
        console.log('DOM already loaded, initializing auto-copy');
        setTimeout(initAutoCopy, 100);
    }

    // Also try to initialize after window load (for Select2 initialization)
    window.addEventListener('load', function() {
        setTimeout(function() {
            console.log('Window loaded, re-initializing auto-copy');
            initAutoCopy();
        }, 500);
    });

})();
